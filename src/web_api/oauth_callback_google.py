import base64
import json
import logging
import typing
import urllib.parse

import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import aws_lambda_powertools.utilities.typing


# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="oauth_callback_google")
_logger.setLevel(level=logging.DEBUG)


@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                         _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:

    parsed_envelope: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model = \
        aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model.model_validate(event)

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

    return {
        "statusCode"    : 200,
        "body"          : "Success"
    }