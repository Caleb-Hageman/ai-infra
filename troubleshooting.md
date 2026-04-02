# Incident Report: Database Outage & Zone Resource Exhaustion

**Service:** PostgreSQL + PGVector (Vector Database)

**Location:** GCP us-east1-b (Migrated to us-east1-c)

**Impact:** Total failure of RAG-based AI chat features across all product teams.

### Time & Root Cause of Zoning Issue
On Sunday (3/29/2026) around 5:00 PM EST, following tests to enhance our RAG capabilities with a minimum similarity score, the GCP e2-micro instance hosting our PostgreSQL + PGVector Docker container was mistakenly scaled down to zero. This happened during a manual effort to save on costs, effectively shutting down the database in the us-east1-b zone.

### Why it impacted other teams and systems
Because the virtual machine was scaled to zero, the database essentially disappeared. This created a bottleneck for the product teams: whenever they made an API request to our chat endpoint, they would hit a timeout error. Our FastAPI Cloud Run instance has to wait for a response from the PGVector database before it can send data to the vLLM Cloud Run instance (the one containing the GPU and LLM). Without that database response, the AI couldn't generate anything.

Problem Identification

On Tuesday (3/31/2026) around 9:30 AM EST, the AI Infra team was attempting to update the service to add rate limiting. We realized then that we couldn't connect to the e2-micro instance. After investigating the GCP UI, we found that the status of our machine was set to "Stopped."

### Challenge: Zonal Resource Exhaustion
The real headache started when we tried to turn the machine back on. We kept hitting a resource error:

    The zone us-east1-b does not have enough resources available to fulfill the request. Try a different zone, or try again later.

Since GCP doesn't provide a time estimate for when resources will open back up, we had no way of knowing how long we would be stuck waiting to restart our instance.

### Resolution
To get things back up, we decided to create a brand new e2-micro instance in a different zone (us-east1-c). We were able to recover the disk from the original instance in us-east1-b, which still held all our data. After mounting that old disk to the new instance, we built a container mapped to it and restored the service.

### Preventive Measures & Recommendations
- **Role-Based Access Control:** We need to restrict access to GCP resources based on roles so that only specific team members have the permission to stop or delete production instances.

- **Internal Team Communication:** We need better communication before making cost-saving changes. We should never scale a service we depend on to zero without a formal check-in to make sure it won't break the pipeline for other teams.

- **Zone Awareness:** Since we are using the free e2-micro tier, we have to remember that if we stop the machine, we might lose our "spot" in that zone. We should treat these instances as "always-on" to avoid getting locked out by resource exhaustion again.