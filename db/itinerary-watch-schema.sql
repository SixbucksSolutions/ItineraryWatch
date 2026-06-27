DROP TABLE monitored_urls;

CREATE TABLE monitored_urls (
    url_id UUID PRIMARY KEY DEFAULT uuidv7(),
    url VARCHAR,
    url_last_scrape_timestamp TIMESTAMP WITH TIME ZONE
);

