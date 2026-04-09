### Incident Report: VM Connectivity Issue (Fedora vs Debian)

**Date:** March 24, 2026  
**Owner:** Infrastructure Team  

---

#### Summary  
Product teams were unable to reach the private API from their GCP VMs. Requests consistently timed out when executed from Fedora-based instances.

---

#### Impact  
- Blocked product teams from testing API endpoints  
- Affected milestone deliverables requiring API interaction  

---

#### Root Cause  
Initial documentation instructed teams to provision Fedora-based VMs.  

While functional in isolated testing, Fedora’s default network/security configuration (notably stricter ingress/egress handling) caused requests to the API to time out in the shared GCP environment.  

This issue did not reproduce in the infra team’s environment due to prior familiarity and local configuration differences.

---

#### Resolution  
Teams were instructed to replace Fedora VMs with Debian-based VMs.  

Debian’s default configuration aligned more directly with GCP networking expectations, allowing successful API communication without additional system-level configuration.

Updated documentation was distributed with:
- Steps to remove existing Fedora instances  
- Steps to provision Debian instances  
- Verified instructions to successfully reach the API  

The original setup document was created by an infrastructure team member using a fresh GCP project to validate the full workflow from initial project configuration through successful API interaction. All steps were executed and verified in a clean environment prior to distribution to ensure reproducibility across teams.

---

#### Status  
Resolved.  
All connectivity issues attributable to VM configuration were eliminated following migration to Debian.