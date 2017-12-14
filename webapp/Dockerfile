FROM ruby:2.4.2-alpine
MAINTAINER Clemens Siebler <clemens.siebler@gmail.com>

RUN apk add --update make gcc g++ libc-dev
RUN gem install rest-client sinatra shotgun haml elasticsearch

RUN mkdir /sinatra
COPY / /sinatra/

# Update ElasticSearch Target
ENV ELASTICSEARCH_HOST=<hostname/ip>:9200
ENV COUCHBASE_REST=http://<hostname/ip>:8093/query/service
ENV COUCHBASE_USERNAME=admin
ENV COUCHBASE_PASSWORD=123456
EXPOSE 8081
ENTRYPOINT ["shotgun", "--host", "0.0.0.0", "--port", "8081", "/sinatra/webapp_cb.rb"]
