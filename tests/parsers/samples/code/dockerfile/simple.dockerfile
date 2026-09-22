FROM analytics AS simple
COPY ./complex.dockerfile /tmp/reference.txt
ENV PIPELINE_STAGE=simple
