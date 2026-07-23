import json
import logging
import requests

import boto3
import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.typing


_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="jwks_updater")
_logger.setLevel(logging.INFO)

_ssm_client = boto3.client("ssm", region_name="us-east-2")

_logger.inject_lambda_context()
@aws_lambda_powertools.utilities.data_classes.event_source(
    data_class=aws_lambda_powertools.utilities.data_classes.EventBridgeEvent)
def lambda_entry_point_event_bridge(_event: aws_lambda_powertools.utilities.data_classes.EventBridgeEvent,
                                    _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    _logger.debug("Starting JWKS Updater")

    # Get latest JSON
    jwks_endpoint: str = "https://www.googleapis.com/oauth2/v3/certs"
    jwks_response: requests.Response = requests.get(jwks_endpoint)

    if not jwks_response.ok:
        _logger.warning(f"JWKS endpoint {jwks_endpoint} returned an error: {jwks_response.status_code}, {jwks_response.reason}")
        return

    _logger.debug(f"HTTP GET of {jwks_endpoint} was successful")

    # De-JSON-ify
    try:
        parsed_jwks_json: dict[str, list[dict]] = jwks_response.json()
    except ValueError as e:
        _logger.warning(f"Could not parse JWKS as JSON: {e}")
        return

    _logger.debug("JSON decode successful")

    if "keys" not in parsed_jwks_json:
        _logger.warning(f"Could not find dict key 'keys' in JWKS: {json.dumps(parsed_jwks_json)}")
        return

    # Convert it from list to dict lookup by key ID
    keys_by_key_id: dict[str, dict[str, str]] = {
        curr_jwk["kid"]: curr_jwk for curr_jwk in parsed_jwks_json["keys"]
    }

    _logger.info(f"Found {len(keys_by_key_id)} key ID's: {json.dumps(list(keys_by_key_id.keys()))}")

    # Write to Parameter Store
    jwks_param_store_key: str = "/itinerary_watch/auth/google/jwks"

    _ssm_client.put_parameter(
        Name        = jwks_param_store_key,
        Value       = json.dumps(keys_by_key_id),
        Overwrite   = True,                             # Most of the time we are overwriting existing
    )

    _logger.info(f"{len(keys_by_key_id)} key ID's written to SSM key {jwks_param_store_key}")
