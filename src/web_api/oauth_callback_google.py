import base64
import functools
import json
import logging
import time
import typing
import urllib.parse
import uuid

import aws_lambda_powertools.utilities.parameters
import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import aws_lambda_powertools.utilities.typing
import boto3
import jwt
import jwt.exceptions
import psycopg

# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="oauth_callback_google")
_logger.setLevel(level=logging.INFO)

# Pass the custom boto3 client into the Powertools SSMProvider to maintain the us-east-2 configuration
_ssm_client = boto3.client("ssm", region_name="us-east-2")
_ssm_provider = aws_lambda_powertools.utilities.parameters.SSMProvider(boto3_client=_ssm_client)

def avoid_warmup_errors(handler):
    @functools.wraps(handler)
    def wrapper(event, context, *args, **kwargs):
        # Intercept the warmer payload before Pydantic parses it
        if isinstance(event, dict) and event.get("source") == "serverless-plugin-warmup":
            _logger.debug("WarmUp: Intercepted ping before Pydantic parser, exiting early")
            return{
                "statusCode"    : 200,
                "body"          : "",
            }

        return handler(event, context, *args, **kwargs)
    return wrapper


@_logger.inject_lambda_context(log_event=True)  # Log all function invocations, even warmup
@avoid_warmup_errors                            # Decorator stack is executed top down, this executes BEFORE the parser middleware
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                         _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:

    # Get the raw body string
    raw_body: str = typing.cast(str, event.body)
    if not raw_body:
        _logger.warning("Received empty body")
        return {
            "statusCode"    : 400,
            "body"          : "Body was empty"
        }

    _logger.debug(f"Raw body: {raw_body}")

    # Intercept and decode base64 if needed
    if event.isBase64Encoded:
        raw_body: str = base64.b64decode(raw_body).decode("utf-8")

    # Now parse inner contents -- will return an empty string if body is not valid form contents
    parsed_query: dict = urllib.parse.parse_qs(raw_body)

    required_keys: set[str] = {"credential", "g_csrf_token"}

    # Test exact key name match constraints
    if len(parsed_query) != 2 or set(parsed_query.keys()) != required_keys:
        _logger.warning(f"Body did not contain form with correct keys: {json.dumps(parsed_query, indent=2)}")
        return {
            "statusCode"    : 400,
            "body"          : f"Body did not contain form with correct keys: {json.dumps(parsed_query, indent=2)}"
        }

    jwt_token: str  = parsed_query.get("credential")[0]
    csrf_token: str = parsed_query.get("g_csrf_token")[0]

    _logger.debug(f"JWT token: {jwt_token}")
    _logger.debug(f"CSRF token: {csrf_token}")

    # Fetch all parameters under this path. Powertools returns a dict with the base path stripped!
    # e.g., keys will be exactly "jwks" and "oauth_client"
    auth_params: dict[str, str] = typing.cast(dict[str, str],
                                              _ssm_provider.get_multiple("/itinerary_watch/auth/google/"))

    _logger.debug("Config data from SSM retrieved successfully")

    google_signing_jwks: dict[str, dict[str, str]] = json.loads(auth_params["jwks"])

    try:
        # 2. Fast extract of the unverified header to locate the 'kid' (Key ID)
        # This takes microseconds because it bypasses cryptographic verification
        key_id: str  = jwt.get_unverified_header(jwt_token).get("kid")

        if key_id not in google_signing_jwks:
            _logger.warning(f"JWT claimed key ID {key_id} but it wasn't found in Google JWKs")
            return {
                "statusCode"    : 401,
                "body"          : f"Matching public certificate for key ID {key_id} not found",
            }

        signing_key: dict[str, str] = google_signing_jwks[key_id]

        # 4. Perform C-accelerated signature evaluation (thanks to jwt[crypto]) and constraint checking
        validated_jwt_claims: dict[str, typing.Any] = jwt.decode(
            jwt_token,
            key=jwt.PyJWK(signing_key).key,
            algorithms=["RS256"],  # Explicitly enforce RS256 to stop substitution exploits
            audience=auth_params["oauth_client"],
            issuer="https://accounts.google.com"
        )

    except jwt.exceptions.ExpiredSignatureError:
        _logger.warning("Security Error: The token has expired.")
        return {
            "statusCode"    : 401,
            "body"          : f"Expired JWT passed"
        }
    except jwt.exceptions.InvalidIssuerError as e:
        _logger.warning(f"Invalid issuer, did not match our OAuth Client ID")
        return {
            "statusCode"    : 401,
            "body"          : "Incorrect iss field"
        }
    except jwt.exceptions.InvalidAudienceError as e:
        _logger.warning(f"Invalid audience: {str(e)}")
        return {
            "statusCode"    : 401,
            "body"          : "Incorrect aud field"
        }
    except jwt.exceptions.InvalidTokenError as e:
        _logger.warning(f"Validation Error: {str(e)}")
        return {
            "statusCode"    : 400,
            "body"          : f"Passed JWT did not pass validation: {e}"
        }

    _logger.info("Successfully validated JWT")
    _logger.info(json.dumps(validated_jwt_claims, indent=2))

    user_id: uuid.UUID = _get_or_assign_user_id(validated_jwt_claims)

    # Set a cookie for JUST api, not needed for www, will be attached and invisible to JavaScript
    # - Omit the "Domain=" property so the browser defaults strictly to current host (api.)
    # - SameSite=Strict ensures it is never passed on cross-origin redirects
    # - HttpOnly blocks malicious frontend JS scripts from stealing the token
    # - Secure guarantees it only travels over encrypted HTTPS links
    cookie_string: str = (
        f"__Host-user_id={str(user_id)}; "
        "Path=/; "
        "SameSite=Strict; "
        "HttpOnly; "
        "Secure; "
        "Max-Age=604800" # Expires in 7 days (60 * 60 * 24 * 7)
    )

    redirect_url: str = "https://www.itinerarywatch.com/watches"

    return {
        "statusCode"    : 302,  # 302 for temporary redirect, 301 for permanent
        "headers"       : {
            "Location"          : redirect_url,

            # Prevent browser caching of this redirect
            "Cache-Control"     : "no-cache, no-store, must-revalidate"
        },

        # Set the auth cookie with user ID for this domain
        "cookies": [cookie_string],

        # Body is required by API Gateway, even if empty
        "body"          : "",
    }


def _get_pg_server_connection_details() -> dict[str, str]:
    # Powertools get_multiple fetches all parameters under the specified path.
    # It automatically strips the path string from the dictionary keys.
    return typing.cast(dict[str, str], _ssm_provider.get_multiple("/itinerary_watch/postgres/"))


def _get_or_assign_user_id(validated_jwt_claims: dict[str, typing.Any]) -> uuid.UUID:
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()

    # Use an upsert query that always returns the user_id
    upsert_query: str = """
        INSERT INTO     users (email) 
        VALUES          (LOWER(%s)) 
        ON CONFLICT     (LOWER(email)) 
        DO UPDATE SET 
            email =     EXCLUDED.email
        RETURNING       user_id;
        """

    logged_in_user_email: str = validated_jwt_claims["email"]

    try:
        # Context manager syntax ("with") gets the connection auto-closed at scope exit, commits if no errors
        #       during connection
        with psycopg.connect(
                host=postgres_connection_params["db_hostname"],
                dbname=postgres_connection_params["db_dbname"],
                user=postgres_connection_params["db_user"],
                password=postgres_connection_params["db_password"],
                sslmode="verify-full",
                sslrootcert="src/aws-rds-global-bundle.pem",
        ) as conn:
            # Context managers for cursors ensure they *also* close automatically
            with conn.cursor() as cur:
                start_time = time.perf_counter()
                cur.execute(upsert_query, (logged_in_user_email,))
                end_time = time.perf_counter()

                result = cur.fetchone()

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise

    # Returns the UUID string
    user_id: uuid.UUID = result[0]

    _logger.info(f"User ID {str(user_id)} retrieved for {logged_in_user_email} in "
                 f"{end_time - start_time:.03f} seconds")

    return user_id