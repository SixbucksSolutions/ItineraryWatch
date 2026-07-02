import base64
import functools
import json
import logging
import time
import typing
import urllib.parse
import uuid

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

_ssm_client = boto3.client("ssm", region_name="us-east-2")


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
    if parsed_envelope.isBase64Encoded:
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

    # Get the signing key data and OAuth client ID out of Parameter Store
    ssm_data: dict[str, str] = _read_parameter_store_params(
        [
            "/itinerary_watch/auth/google/jwks",
            "/itinerary_watch/auth/google/oauth_client",
        ]
    )

    _logger.debug(f"Config data from SSM: {json.dumps(ssm_data, indent=2)}")

    google_signing_jwks: dict[str, dict[str, str]] = json.loads(ssm_data["/itinerary_watch/auth/google/jwks"])

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
            audience=ssm_data["/itinerary_watch/auth/google/oauth_client"],
            issuer="https://accounts.google.com"
        )

    except jwt.exceptions.ExpiredSignatureError:
        _logger.warning("Security Error: The token has expired.")
        return {
            "statusCode"    : 401,
            "body"          : f"Expired JWT passed"
        }
    except jwt.exceptions.InvalidIssuerError as e:
        _logger.warning(f"Invalid issuer, did not match our OAuth Client ID of {ssm_data}")
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

    # Redirect to watches list for this user with their user ID as a query parameter
    base_url = "https://www.itinerarywatch.com/watches"
    parsed_url = urllib.parse.urlparse(base_url)

    # Safely encode the query parameters
    params = {
        "user_id": str(user_id),
    }

    encoded_query = urllib.parse.urlencode(params)

    # Components structure: (scheme, netloc, path, params, query, fragment)
    url_components = (
        parsed_url.scheme,  # 'https'
        parsed_url.netloc,  # 'www.firsttracks.net'
        parsed_url.path,  # '/watches'
        parsed_url.params,  # ''
        encoded_query,  # 'user_id=12345'
        parsed_url.fragment  # ''
    )

    # Generate the finalized validated URL string
    redirect_url: str = urllib.parse.urlunparse(url_components)

    return {
        "statusCode"    : 302,  # 302 for temporary redirect, 301 for permanent
        "headers"       : {
            "Location"          : redirect_url,

            # Prevent browser caching of this redirect
            "Cache-Control"     : "no-cache, no-store, must-revalidate"
        },

        # Body is required by API Gateway, even if empty
        "body"          : "",
    }


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


def _get_pg_server_connection_details() -> dict[str, str]:
    db_params_keys: list[str] = [
        "/itinerary_watch/postgres/db_hostname",
        "/itinerary_watch/postgres/db_dbname",
        "/itinerary_watch/postgres/db_user",
        "/itinerary_watch/postgres/db_password",
    ]

    returned_params: dict[str, str] = _read_parameter_store_params(db_params_keys)

    return_dict: dict[str, str] = {}
    for curr_key in db_params_keys:
        # shorten to final token
        return_dict[curr_key.split("/")[-1]] = returned_params[curr_key]

    return return_dict


def _get_or_assign_user_id(validated_jwt_claims: dict[str, typing.Any]) -> uuid.UUID:
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()

    # Use an upsert query that always returns the user_id
    upsert_query: str = """
    INSERT INTO             users (email) 
    VALUES                  (%s)
    ON CONFLICT (email) 
        DO UPDATE           SET email = EXCLUDED.email
    RETURNING               user_id;
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
