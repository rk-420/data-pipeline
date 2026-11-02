# AWS setup guide

This guide sets up the cloud part of the pipeline in your own AWS account:

```
EventBridge Scheduler (daily 06:00) ──► Lambda "energy-extract" ──► S3 raw/
Laptop: python src/pipeline.py ──► S3 raw/ + S3 processed/ (Parquet, one file per day)
S3 processed/ ──► Glue Data Catalog table ──► Athena SQL queries
```

Everything runs in **eu-central-1 (Frankfurt)**. Do the steps in order. Each
command block can be pasted into the terminal (zsh) from the project root.

---

## Costs: read this first

This project stores a few MB of data and runs one short Lambda per day, so the
expected cost is **close to €0 per month**. Prices below are AWS list prices at
the time of writing; check the linked pricing pages, because they change.

| Service | What we use | Price | Expected cost |
|---|---|---|---|
| S3 | ~10 MB of JSON + Parquet | ~$0.025 per GB-month | < $0.01 / month |
| Lambda | 30 runs/month, ~25 s, 256 MB | 1M requests + 400,000 GB-s free every month | $0 |
| EventBridge Scheduler | 30 invocations/month | 14M invocations free every month | $0 |
| Glue Data Catalog | 1 database, 1 table | first 1M objects free | $0 |
| Athena | a few queries over a few MB | $5 per TB scanned, min. 10 MB per query | ~$0.00005 per query |
| CloudWatch Logs | a few KB per day | 5 GB free every month | $0 |

**What could cost money, and how this guide avoids it:**

- **Glue crawlers** cost about $0.44 per DPU-hour and are billed per run. We do
  **not** use a crawler: the table is defined by hand with *partition
  projection*, which is free and finds new days automatically.
- **Athena queries on lots of data.** The workgroup below has a hard limit of
  1 GB scanned per query (about half a cent), so a mistake can't get expensive.
- **Forgotten resources.** Everything is listed in [Cleanup](#cleanup) at the end.
- **Logs kept forever.** The log group gets a 14-day retention.
- **Never** make the bucket public, and never commit access keys.

> **Step 0 – set a budget alarm before anything else.** In the AWS console,
> open **Billing and Cost Management → Budgets → Create budget**, choose the
> template **"Zero spend budget"**, and enter your email. AWS emails you as soon
> as anything costs more than $0.01.

---

## Step 1 – Account security and AWS CLI

1. **Protect the root user.** Sign in as root once, open **Security credentials**
   and enable **MFA**. Don't use the root user for daily work and never create
   access keys for it.
2. **Create an admin user for the setup.** IAM → Users → Create user, name
   `energy-admin`, attach the policy `AdministratorAccess`, enable MFA. Then,
   under *Security credentials → Create access key → Command Line Interface*,
   create an access key. (This user creates the resources below. The pipeline
   itself later gets its own user with far fewer permissions.)
3. **Install the AWS CLI** (needs ~200 MB of disk space) and log in:

```zsh
brew install awscli
aws configure --profile energy-admin
#   AWS Access Key ID:     <paste from step 2>
#   AWS Secret Access Key: <paste from step 2>
#   Default region name:   eu-central-1
#   Default output format: json
```

The keys are saved in `~/.aws/credentials` on your Mac, **outside the project**,
so they can never end up in git.

---

## Step 2 – Variables used by all following commands

```zsh
export AWS_PROFILE=energy-admin
export AWS_REGION=eu-central-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# Bucket names are global across all AWS accounts, so add the account ID
export BUCKET=energy-data-pipeline-$ACCOUNT_ID
echo "Account $ACCOUNT_ID, bucket $BUCKET"
```

If you open a new terminal later, run this block again.

---

## Step 3 – S3 bucket (the data lake)

```zsh
aws s3api create-bucket --bucket $BUCKET \
    --create-bucket-configuration LocationConstraint=$AWS_REGION

# Block all public access (default for new buckets, set explicitly to be sure)
aws s3api put-public-access-block --bucket $BUCKET \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Delete Athena's result files after 7 days, so they don't pile up
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration '{
  "Rules": [{"ID": "expire-athena-results", "Status": "Enabled",
             "Filter": {"Prefix": "athena-results/"},
             "Expiration": {"Days": 7}}]}'
```

**Folder layout** (S3 has no real folders; these are key prefixes):

| Prefix | Content | Written by |
|---|---|---|
| `raw/run_date=YYYY-MM-DD/<series>/<chunk>.json` | untouched SMARD responses | Lambda + laptop pipeline |
| `processed/energy_hourly/dt=YYYY-MM-DD/data.parquet` | cleaned data, one file per day | laptop pipeline |
| `athena-results/` | query results | Athena |

---

## Step 4 – Fill in the IAM policies

The policies in `aws/iam/` contain the placeholders `YOUR_BUCKET` and
`YOUR_ACCOUNT_ID`. This creates filled-in copies in `dist/iam/` (ignored by git):

```zsh
mkdir -p dist/iam
for f in aws/iam/*.json; do
  sed "s/YOUR_BUCKET/$BUCKET/g; s/YOUR_ACCOUNT_ID/$ACCOUNT_ID/g" "$f" > "dist/iam/$(basename $f)"
done
ls dist/iam
```

### What each identity may do (least privilege)

| Identity | Allowed | Not allowed (examples) |
|---|---|---|
| **Lambda role** `energy-extract-lambda` | write objects under `raw/` in this bucket; write to its own log group | read anything, delete anything, touch `processed/`, other buckets |
| **Scheduler role** `energy-extract-scheduler` | invoke the `energy-extract` function | invoke any other function, anything else |
| **Pipeline user** `energy-pipeline` (your laptop) | write `raw/` and `processed/`; read `processed/`; run Athena in the `energy` workgroup; read the Glue table | delete objects, create/delete tables, IAM, other buckets |

A **trust policy** says *who* may use a role (e.g. only the Lambda service).
A **permissions policy** says *what* the role may do.

---

## Step 5 – Lambda function

```zsh
# Role for the function
aws iam create-role --role-name energy-extract-lambda \
    --assume-role-policy-document file://dist/iam/lambda-trust-policy.json
aws iam put-role-policy --role-name energy-extract-lambda \
    --policy-name energy-extract-permissions \
    --policy-document file://dist/iam/lambda-permissions-policy.json

# Log group with 14-day retention (otherwise logs are kept forever)
aws logs create-log-group --log-group-name /aws/lambda/energy-extract
aws logs put-retention-policy --log-group-name /aws/lambda/energy-extract \
    --retention-in-days 14

# Build the code package (dist/lambda.zip, ~1 MB)
zsh aws/build_lambda.sh

# A new role needs a few seconds before Lambda can use it
sleep 10

aws lambda create-function --function-name energy-extract \
    --runtime python3.13 --architectures arm64 \
    --handler lambda_function.handler \
    --role arn:aws:iam::$ACCOUNT_ID:role/energy-extract-lambda \
    --zip-file fileb://dist/lambda.zip \
    --timeout 120 --memory-size 256 \
    --environment "Variables={S3_BUCKET=$BUCKET,WEEKS=2}"
```

**Test it once by hand:**

```zsh
aws lambda invoke --function-name energy-extract \
    --cli-binary-format raw-in-base64-out --payload '{}' dist/response.json
cat dist/response.json
aws s3 ls s3://$BUCKET/raw/ --recursive | head
aws logs tail /aws/lambda/energy-extract --since 10m
```

Expected response: `{"status": "ok", "run_date": "...", "files_uploaded": 10}`
(5 series × 2 weeks).

**After code changes**, rebuild and upload the new package:

```zsh
zsh aws/build_lambda.sh
aws lambda update-function-code --function-name energy-extract \
    --zip-file fileb://dist/lambda.zip
```

---

## Step 6 – Daily schedule (EventBridge Scheduler)

```zsh
aws iam create-role --role-name energy-extract-scheduler \
    --assume-role-policy-document file://dist/iam/scheduler-trust-policy.json
aws iam put-role-policy --role-name energy-extract-scheduler \
    --policy-name invoke-energy-extract \
    --policy-document file://dist/iam/scheduler-permissions-policy.json

sleep 10

# Every day at 06:00 German time (handles summer/winter time automatically)
aws scheduler create-schedule --name energy-extract-daily \
    --schedule-expression "cron(0 6 * * ? *)" \
    --schedule-expression-timezone Europe/Berlin \
    --flexible-time-window Mode=OFF \
    --target "Arn=arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:energy-extract,RoleArn=arn:aws:iam::$ACCOUNT_ID:role/energy-extract-scheduler"
```

Check the next morning with `aws logs tail /aws/lambda/energy-extract --since 1d`.

---

## Step 7 – Pipeline user for your laptop

```zsh
aws iam create-user --user-name energy-pipeline
aws iam put-user-policy --user-name energy-pipeline \
    --policy-name energy-pipeline \
    --policy-document file://dist/iam/pipeline-user-policy.json
aws iam create-access-key --user-name energy-pipeline
```

Copy `AccessKeyId` and `SecretAccessKey` from the output into a new profile:

```zsh
aws configure --profile energy-pipeline
```

Then set these lines in your project `.env` (the bucket name is printed by `echo $BUCKET`):

```
S3_BUCKET=energy-data-pipeline-<your account id>
AWS_PROFILE=energy-pipeline
AWS_DEFAULT_REGION=eu-central-1
```

Now `python src/pipeline.py` runs step 4 and uploads raw JSON and daily
Parquet files to S3. Check with:

```zsh
AWS_PROFILE=energy-pipeline aws s3 ls s3://$BUCKET/processed/energy_hourly/ | tail -3
```

---

## Step 8 – Athena workgroup, Glue table and queries

```zsh
# Workgroup: stores results in our bucket and stops any query that would
# scan more than 1 GB (a cost safety net)
aws athena create-work-group --name energy --configuration \
    "ResultConfiguration={OutputLocation=s3://$BUCKET/athena-results/},EnforceWorkGroupConfiguration=true,BytesScannedCutoffPerQuery=1073741824"
```

Then in the AWS console open **Athena → Query editor**, choose the workgroup
**energy** (top right), and run, one statement at a time:

1. `sql/athena/01_create_database.sql`
2. `sql/athena/02_create_table.sql`, after replacing both `YOUR_BUCKET` with your bucket name
3. The queries in `sql/athena/03_example_queries.sql`

The table now appears in **AWS Glue → Data Catalog → Tables**. Athena shows
"Data scanned" under each result: for this project it is a few hundred KB.

**Why no Glue crawler?** A crawler scans S3 and guesses the schema. It costs
money per run and must run again for every new day. We know our schema exactly,
so a hand-written `CREATE EXTERNAL TABLE` is free, precise and reviewable in git.
*Partition projection* tells Athena that partitions are named `dt=YYYY-MM-DD`,
so new days are queryable immediately, with no crawler and no `MSCK REPAIR TABLE`.

---

## Cleanup

To delete everything (e.g. after the application process), run Step 2 again, then:

```zsh
aws scheduler delete-schedule --name energy-extract-daily
aws lambda delete-function --function-name energy-extract
aws logs delete-log-group --log-group-name /aws/lambda/energy-extract
aws iam delete-role-policy --role-name energy-extract-lambda --policy-name energy-extract-permissions
aws iam delete-role --role-name energy-extract-lambda
aws iam delete-role-policy --role-name energy-extract-scheduler --policy-name invoke-energy-extract
aws iam delete-role --role-name energy-extract-scheduler
aws athena delete-work-group --work-group energy --recursive-delete-option
aws glue delete-table --database-name energy --name energy_hourly
aws glue delete-database --name energy
# Pipeline user: first delete its access key (ID from "aws iam list-access-keys --user-name energy-pipeline")
aws iam delete-access-key --user-name energy-pipeline --access-key-id <KEY_ID>
aws iam delete-user-policy --user-name energy-pipeline --policy-name energy-pipeline
aws iam delete-user --user-name energy-pipeline
# Deletes all data in the bucket, then the bucket. This cannot be undone.
aws s3 rb s3://$BUCKET --force
```
