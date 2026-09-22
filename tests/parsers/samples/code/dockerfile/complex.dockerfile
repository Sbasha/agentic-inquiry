FROM python:3.11-slim AS analytics
RUN pip install numpy
ENV PIPELINE_STAGE=complex
