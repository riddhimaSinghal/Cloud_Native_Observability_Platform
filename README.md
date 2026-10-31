# AI-Powered Cloud Infrastructure Monitoring and Predictive Failure Detection (AWS)

A small cloud-native observability platform. It collects CPU, memory, disk and network metrics, uses an
**Isolation Forest** (scikit-learn) to detect anomalies, estimates a **failure risk (0-100%)**, shows everything on a
live **React + Chart.js** dashboard, and e-mails administrators through **Amazon SNS** when a critical anomaly appears.

![Architecture](docs/architecture.svg)

**Honest status:** the application, ML model and tests run and pass locally with simulated data. The CloudFormation
template passes `cfn-lint`, but **it has not been deployed to a real AWS account by the author of this code**. The SNS,
DynamoDB and CloudWatch code paths are covered by tests that use fakes, not real AWS. Follow Part 2 and expect to
fix small environment-specific issues (see Troubleshooting).

## What is in the project

```
backend/            FastAPI app, ML model, alerting, tests
  app/collector.py    real (psutil) or simulated metrics + fault injection
  app/ml.py           Isolation Forest, anomaly score, failure risk, severity
  app/alerts.py       SNS e-mail alerts (consecutive-sample rule + cool-down)
  app/storage.py      in-memory history + optional DynamoDB
  app/cloudwatch.py   publishes custom metrics (optional)
  app/engine.py       collect -> analyse -> store -> alert loop
  app/main.py         REST API, security headers, serves the dashboard
  tests/              19 automated tests (pytest)
  evaluate_model.py   reproduces the accuracy table in the report
frontend/           React + Chart.js dashboard (Vite). frontend/dist is pre-built
infrastructure/cloudformation.yaml   whole AWS stack
docs/               architecture.svg, REPORT.md
scripts/            run_local.sh, package.sh
```

## Part 1 - Run locally (no AWS needed)

Requirements: Python 3.10+ (Node.js 18+ only if you want to edit the dashboard).

```bash
./scripts/run_local.sh          # creates a venv, installs packages, starts the server
```
or manually:
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```
Open **http://localhost:8000**. The API key for the demo controls is `demo-key` (change it in `backend/.env`,
see `.env.example`).

**Demo workflow (about 1 minute)**
1. Watch the dashboard: status is *Healthy*, risk about 0%.
2. Type `demo-key` in *Demo controls* and click **Full failure** (or **Memory leak**).
3. Within a few seconds the charts climb, the risk gauge turns red, rows appear in *Anomaly history*.
4. After 2 consecutive critical samples an entry appears under *Alerts sent*. Locally it says
   "Logged locally (SNS not configured)" - on AWS the same step sends the e-mail.

Run the tests: `cd backend && python -m pytest -q` (expected: 19 passed).
Model evaluation: `cd backend && python evaluate_model.py`.

Dashboard development (hot reload): `cd frontend && npm install && npm run dev` -> http://localhost:5173
(the backend must be running on port 8000). Rebuild the production bundle with `npm run build`.

To monitor your own machine instead of simulated data: `METRICS_SOURCE=real uvicorn app.main:app`. The model first
learns for `MIN_TRAIN_SAMPLES` (60) samples, about 2 minutes at the default 2 s interval. The demo buttons still work
because they add a fault on top of the real readings (marked "injected").

## Part 2 - Deploy on AWS

Prerequisites: an AWS account, the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
configured (`aws configure`), and Python/Node only if you rebuild the zip. Pick one region and use it everywhere
(examples use `ap-south-1`).

**Step 1 - Package the code**
```bash
./scripts/package.sh            # builds the dashboard and writes cad-monitor.zip
```

**Step 2 - Upload to S3** (bucket names are global, so choose a unique one)
```bash
export REGION=ap-south-1
export BUCKET=cad-monitor-code-<your-unique-suffix>
aws s3 mb s3://$BUCKET --region $REGION
aws s3 cp cad-monitor.zip s3://$BUCKET/cad-monitor.zip --region $REGION
```

**Step 3 - Find your VPC, a public subnet and your IP**
```bash
aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text --region $REGION
aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC_ID> --query "Subnets[*].[SubnetId,AvailabilityZone,MapPublicIpOnLaunch]" --output table --region $REGION
curl -s https://checkip.amazonaws.com     # your public IP -> use <IP>/32
```

**Step 4 - Create the stack**
```bash
aws cloudformation deploy \
  --region $REGION \
  --stack-name cad-monitor \
  --template-file infrastructure/cloudformation.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      AlertEmail=you@example.com \
      ApiKey='choose-a-long-secret' \
      AllowedCidr=<YOUR_IP>/32 \
      VpcId=<VPC_ID> SubnetId=<SUBNET_ID> \
      CodeBucket=$BUCKET
```
(Console alternative: CloudFormation -> Create stack -> upload `infrastructure/cloudformation.yaml` -> fill the same parameters.)

**Step 5 - Confirm the e-mail subscription.** AWS sends "AWS Notification - Subscription Confirmation" to your address.
Click *Confirm subscription*. **No alert e-mails are delivered until you do.**

**Step 6 - Open the dashboard**
```bash
aws cloudformation describe-stacks --stack-name cad-monitor --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='DashboardUrl'].OutputValue" --output text
```
Wait about 4 minutes after the stack finishes (software installs at first boot). The dashboard shows
"learning" for about 5 minutes (60 samples x 5 s) while the model learns this server's normal behaviour.

**Step 7 - Demonstrate the complete workflow**
1. Enter your `ApiKey` in *Demo controls*, click **Full failure**.
2. Watch the metrics rise, the gauge go red and the anomaly appear in the history table.
3. Check your inbox for `[CRITICAL] <host>: failure risk NN%`. The *Alerts sent* table shows "Email via SNS".
4. In the AWS console: CloudWatch -> Metrics -> `CADMonitor` (custom metrics); CloudWatch -> Alarms
   (`cad-monitor-ml-failure-risk` goes to ALARM and sends its own e-mail too); DynamoDB -> Tables -> `cad-monitor-metrics`
   -> Explore items (stored history).

**Step 8 - Clean up (to stop charges)**
```bash
aws cloudformation delete-stack --stack-name cad-monitor --region $REGION
aws s3 rb s3://$BUCKET --force --region $REGION
```

### Troubleshooting
| Symptom | Check |
|---|---|
| Dashboard does not load | Wait 5 min; is `AllowedCidr` your *current* IP? Subnet must be public. |
| Still blank after 10 min | Session Manager: `aws ssm start-session --target <InstanceId>` then `sudo tail -n 80 /var/log/cloud-init-output.log` and `sudo journalctl -u cad-monitor -n 50`. |
| `aws s3 cp` fails in the boot log | The bucket must be in the same region and `CodeKey` must match the uploaded file name. |
| No e-mail | Did you confirm the subscription? Check spam. `sudo journalctl -u cad-monitor | grep -i sns`. |
| Integration chips show "off" | They reflect real configuration: SNS/DynamoDB/CloudWatch are only "on" when the env file has the values (set by the template). |

## How it works (short)

1. **Collect** every `TICK_INTERVAL` seconds (psutil on EC2, or the simulator locally).
2. **Detect** with an Isolation Forest on 7 features (5 raw metrics + `peak_util` and `net_total`). Output: anomaly score 0-100.
3. **Estimate risk** = 50% anomaly score + 50% resource pressure (how far the busiest of CPU/memory/disk is above 60%).
   Severity: `<30` normal, `30-54` warning, `55-74` high, `>=75` critical.
4. **Store** in memory (dashboard) and DynamoDB (history, 24 h TTL); publish `FailureRisk` etc. to CloudWatch.
5. **Alert**: 2 consecutive critical samples -> SNS e-mail, then a 60 s cool-down.
6. **Retrain** automatically every 300 samples on recent non-injected normal data (or press *Retrain model*).

## Security measures
- Security group allows only port 80 from your CIDR; **no SSH** (use SSM Session Manager).
- Least-privilege IAM role (publish to one topic, put items in two tables, one S3 object, CloudWatch namespace `CADMonitor`).
- IMDSv2 required, encrypted EBS volume, encrypted DynamoDB tables.
- `X-API-Key` (constant-time comparison) protects `/api/simulate`, `/api/simulate/stop`, `/api/retrain`.
- Strict input validation (scenario names are an enum, query limits bounded), CORS allow-list, security headers.
- Service runs as a non-root user with `NoNewPrivileges`.

**Known limitations (be upfront about these in your viva):** traffic is plain HTTP, so the API key travels unencrypted -
for production put an Application Load Balancer with an ACM certificate in front (not included to keep cost low).
The API key is stored in EC2 user-data (use Secrets Manager/SSM Parameter Store in production). Read-only dashboard
endpoints are unauthenticated and rely on the IP allow-list. Single server, no high availability.

## Configuration
All settings are environment variables - see `backend/.env.example`.

## API
`GET /api/health` - `GET /api/overview` - `GET /api/anomalies` - `GET /api/alerts` -
`POST /api/simulate {"scenario": "..."}` - `POST /api/simulate/stop` - `POST /api/retrain` (POSTs need `X-API-Key`).
Interactive docs at `/docs`.
