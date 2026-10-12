# FarmCraft 30-team rehearsal cost

- VM starts: 2026-10-12 14:51:36 UTC, observed in Azure Activity Log.
- VM deallocation: 2026-10-12T15:25:37+00:00.
- Running hours per additional VM: 0.567.
- Estimated incremental VM compute: US$0.26 at US$0.236/h (D4s v4) plus US$0.216/h (D4as v4).
- Estimated retained disk and public IP cost over the same interval: US$0.01 at US$0.0142/h combined.
- Estimated 3-hour event additional VM compute: US$1.36, plus approximately US$0.04 disk/IP over those hours.
- Azure Container Apps, PostgreSQL, Blob, log ingestion, transactions, and existing baseline are additional; no current invoice or posted actual usage was available to this runner.
- Last user-reported student credit before this run: ₹9,174 of ₹9,599. Current remaining credit was not independently verified.

These are estimates, not Azure billed amounts. Deallocated VMs retain disks and public IPs, which can continue billing.
Azure [Cost Management data can arrive after usage occurs](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data); compare this estimate with posted usage later.
