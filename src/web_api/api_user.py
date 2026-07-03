import functools
import json
import logging
import typing

import aws_lambda_powertools.utilities.typing
import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import boto3

from . import auth

# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="api")
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
@avoid_warmup_errors                            # This docorator executes BEFORE the parser middleware
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                         _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:
    authenticated_user_info: dict[str, typing.Any] | None = auth.authenticated_user(event)

    if not authenticated_user_info:
        return {
            "statusCode": 401,
            "headers": {
                "Content-Type"                      : "application/json",
                "WWW-Authenticate"                  : "Cookie realm=\"://api.itinerarywatch.com\""
            },
            "body": json.dumps(
                {
                    "error": "Unauthorized",
                    "message": "Auth failed; secure session context is missing or invalid"
                }
            ),
        }

    return {
        "statusCode"    : 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body"          : json.dumps(authenticated_user_info),
    }
