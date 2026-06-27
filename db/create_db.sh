#!/usr/bin/bash

CREATEDB="/usr/bin/createdb"

${CREATEDB} --host ${RDSHOST} --username postgres itinerary-watch
