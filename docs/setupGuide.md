# GCP Setup Guide

#### Notes:
1) if at any point you run into an error saying that a command doesn't exist, google how to install the command on your OS and do that before proceeding.
2) if you're prompted to enable some google service on your project, do it. sometimes this will be time consuming.
3) the project id that steps 1, 13, 14, 15 refer to is the one from gcp, you can find it by running `gcloud config get-value project`
4) the project id in step 24 is the long one which will look like (but not exactly be) "462c233d-0364-443f-a822-cd847cb84d12"
5) anywhere there's a <text>, remove both < and > and put your text in it's place. for "<text>", keep the quotes but still remove < and >
6) steps 24 through 30 are how to get a script to do the 20 calls to chat for the PRR document. i found it easier than individually running and evaluating them, but you don't have to do those steps they're just convenient.

---

#### Peering Handshake Setup

1. Set project:
   ```bash
   gcloud config set project <insert your project id from google cloud>
   ```
2. Create VPC:
   ```bash
   gcloud compute networks create <edu / lgl / med>-vpc --subnet-mode=custom
   ```
3. Create Subnet:
   ```bash
   gcloud compute networks subnets create <edu / lgl / med>-sub /
   --network=<edu / lgl / med>-vpc /
   --range=10.0.<2 / 3 / 4>.0/24 /
   --region=us-east1 /
   ```
4. Create peering to infra:
   ```bash
   gcloud compute networks peerings create <edu / lgl / med>-to-inf \
   --network=<edu / lgl / med>-vpc \
   --peer-project=indigo-bedrock-487015-g2 \
   --peer-network=inf-vpc
   ```
5. Allow ingress from peered networks:
```bash
gcloud compute firewall-rules create allow-peered-teams \
  --network=<edu / lgl / med>-vpc \
  --action=ALLOW \
  --direction=INGRESS \
  --rules=tcp:80,tcp:443,tcp:8000,tcp:8080 \
  --source-ranges=10.0.1.0/24,10.0.2.0/24,10.0.3.0/24,10.0.4.0/24,10.0.5.0/24,10.0.6.0/24 \
  --priority=1000
   ```
6. Verify peering:
```bash
gcloud compute networks peerings list 
--network=<edu / lgl / med>-vpc
```
7. Allow egress to infra:
```bash
gcloud compute firewall-rules create allow-egress-to-infra \
  --network=<edu / lgl / med>-vpc \
  --action=ALLOW \
  --direction=EGRESS \
  --destination-ranges=10.0.1.0/24 \
  --rules=tcp:80,tcp:443,tcp:8080
```

---

#### Updated VM Deployment and Setup

> NOTE:
> This is where the issue occurred. The previous document used a Fedora Linux VM,
> which has stricter default networking rules that can block traffic.
>
> If you already created a VM using the original document, delete it:
gcloud compute instances delete ai-infra-test --zone=us-east1-c -q
> (or us-east1-b or us-east1-d, depending on your zone)
>
> Wait a few minutes for deletion to complete, then proceed with steps 17–30.

8. Install Google Cloud CLI on your local machine (Google instructions)

9. Download the Dockerfile sent to #general on the 17th and place it in your working directory

10. Authenticate Docker with GCP:
```bash
gcloud auth configure-docker us-east1-docker.pkg.dev
```

11. Create artifact repository:
```bash
gcloud artifacts repositories create test \
  --repository-format=docker \
  --location=us-east1
```

12. Build Docker image:
```bash
docker build -f Dockerfile.productTest -t product-test .
```

13. Tag image:
```bash
docker tag product-test us-east1-docker.pkg.dev/<INSERT YOUR ID FROM GCP>/test/product-test
```

14. Push image:
```bash
docker push us-east1-docker.pkg.dev/<INSERT YOUR ID FROM GCP>/test/product-test
```

15. Deploy to Cloud Run:
```bash
gcloud run deploy product-test \
  --image us-east1-docker.pkg.dev/<INSERT YOUR ID FROM GCP>/test/product-test \
  --region us-east1 \
  --platform managed \
  --allow-unauthenticated
```

16. Limit instances:
```bash
gcloud run services update product-test \
  --max-instances=3 \
  --region=us-east1
```

17. Create VM (Debian):
```bash
    gcloud compute instances create ai-infra-test \
    --zone=us-east1-b \
    --machine-type=e2-micro \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --network=<edu / lgl / med>-vpc \
    --subnet=<edu / lgl / med>-sub \
    --scopes=cloud-platform
```

> 17.1 NOTE:
> If you see "could not fetch resource":
> - Change zone b to c or d (must remain us-east1)
> - You can try different machine types
> - Region MUST remain us-east1

18. SSH into VM:
    ```bash
    gcloud compute ssh ai-infra-test --zone=us-east1-b
    ```
> (or c/d if changed above)

19. Install dependencies inside VM:
    ```bash
    sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates gnupg curl
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
    sudo apt-get update && sudo apt-get install -y google-cloud-cli
    ```

> 19.1 NOTE:
> If pasting fails, you may need to type commands manually
> Installation can take 15–20 minutes

---

#### Update since former document:
20. 
```bash
exit
```
21. 
```bash
gcloud compute networks peerings update <edu / lgl / med>-to-inf \
--network=<edu / lgl / med>-vpc \
--import-custom-routes \
--export-custom-routes
```
23. 
```bash
gcloud compute ssh ai-infra-test --zone=us-east1-b (or c or d if you changed it in step 17)
```
24. 
```bash
curl 10.0.1.5
```
   > 23.1. If that still isn't giving you "hello world", contact me directly and we can work on it in person during lab.
