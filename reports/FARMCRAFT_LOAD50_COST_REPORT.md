# FarmCraft 50-team Azure staging cost estimate

The test reused two existing Azure for Students VMs; it created no new compute, storage account, database server, or public IP resource.

| VM | Azure region | Size | Verified Linux retail rate | Start observed in Activity Log | Stop evidence |
| --- | --- | --- | ---: | --- | --- |
| `farmcraft-eval-02` | Korea Central | Standard D4s v4 | US$0.236/h | 2026-10-12 20:54:16 UTC | Deallocation succeeded 21:27:52 UTC |
| `farmcraft-eval-03` | Indonesia Central | Standard D4as v4 | US$0.216/h | 2026-10-12 20:55:05 UTC | `VM deallocated` verified before 21:30 UTC; Activity Log completion timestamp not yet returned |

The [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) returned these rates on 2026-10-13 IST. The Korean VM's observed interval implies about **US$0.132** of compute at the retail rate. Using the 21:30 UTC verification time as a conservative bound for the Indonesian VM gives at most about **US$0.126**, or **less than US$0.26 combined compute** for this run. This is an estimate from resource time and retail rates, not a billed charge. Azure may apply different subscription prices, credits, rounding, or later corrections.

The same two VMs running for a three-hour event would project to **US$1.356 in VM compute** at those rates. The prior local estimate for retained managed disks and public IPs was about US$0.0142/hour combined; if unchanged, that is about US$0.01 during this rehearsal and US$0.04 over three hours. PostgreSQL, Container Apps, Blob storage, network egress, log ingestion, and existing baseline costs are additional. Managed disks and reserved IPs may continue billing after VM deallocation.

The latest user-reported Azure for Students balance before this test was ₹9,174 of ₹9,599; no current balance was independently returned by the Azure API. No current invoice or posted usage for this run was available. [Azure Cost Management data can arrive with a delay and may be rerated](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data); compare the estimate with posted usage when it appears.
