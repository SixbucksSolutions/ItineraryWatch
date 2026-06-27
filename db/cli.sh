#!/usr/bin/bash

PSQL="/usr/bin/psql"

${PSQL} "host=$RDSHOST port=5432 dbname=postgres user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem"
