FROM simple AS dynamic
COPY ./simple.dockerfile /tmp/simple-reference.txt
CMD ["/bin/bash", "-lc", "echo dynamic-stage"]
