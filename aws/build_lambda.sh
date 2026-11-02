#!/bin/zsh
# Build the Lambda deployment package: dist/lambda.zip
# Run from the project root:  zsh aws/build_lambda.sh
#
# The zip contains our code + the "requests" library. boto3 is already
# included in the Lambda Python runtime, so it is not packaged.
set -euo pipefail

BUILD=dist/lambda_build
rm -rf "$BUILD" dist/lambda.zip
mkdir -p "$BUILD"

# Lambda runs Linux on ARM (arm64, cheaper than x86), Python 3.13.
# --platform makes pip download Linux packages even though we are on a Mac.
pip install --quiet requests --target "$BUILD" \
    --platform manylinux2014_aarch64 --python-version 3.13 \
    --only-binary=:all: --implementation cp

cp aws/lambda_function.py src/extract.py src/s3_upload.py src/logging_setup.py "$BUILD"/

(cd "$BUILD" && zip -qr ../lambda.zip .)
rm -rf "$BUILD"
echo "Built dist/lambda.zip ($(du -h dist/lambda.zip | cut -f1))"
