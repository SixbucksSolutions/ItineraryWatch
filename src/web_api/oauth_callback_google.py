import typing

import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import aws_lambda_powertools.utilities.typing


# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="oauth_callback_google")


@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(_event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                          _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:


    return {
        "statusCode"    : 200,
        "body"          : "Success"
    }