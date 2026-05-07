#!/bin/bash

docker build -t nfc-csv-analyzer -f Dockerfile-dev .

docker run --rm -it \
    --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
    --name nfc-csv-analyzer \
    -v /"$(pwd)":/workspace \
    -w //workspace \
    nfc-csv-analyzer:latest
