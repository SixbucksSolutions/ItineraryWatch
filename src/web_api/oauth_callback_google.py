import base64
import json
import logging
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
_logger.setLevel(level=logging.DEBUG)

_ssm_client = boto3.client("ssm", region_name="us-east-2")


@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                         _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:

    try:
        parsed_envelope: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model = \
            aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model.model_validate(event)
    except ValueError as e:
        _logger.warning(f"Failed pydantic model validation: {e}")
        return {
            "statusCode"    : 400,
            "body"          : f"Failed pydantic model validation: {e}"
        }

    # 1. Get the raw body string
    raw_body: str = typing.cast(str, parsed_envelope.body)
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

    return {
        "statusCode"    : 200,
        "body"          : "Success"
    }


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


def _get_or_assign_user_id(validated_jwt_claims: dict[str, typing.Any]) -> uuid.UUID:
    pass