# FarmCraft event readiness checklist

- [x] 30 official Round 1 jobs and 180 games audited.
- [x] Full 16-team bracket, replay frames, and final independently audited.
- [x] Champion persisted in Azure staging.
- [x] Post-run private backup created and hash-checked.
- [x] Test accounts/jobs removed; competition phase SETUP; public gates MAINTENANCE.
- [x] Two additional evaluator VMs deallocated.
- [ ] Authenticated Admin and contestant browser walkthrough. Only API and public UI were checked here.
- [ ] Separate invalid-source HTTP fixture and UI error presentation.
- [ ] Review reference-bot difficulty or tie-break policy: all 30 rehearsal bots reached rating 1000.
- [ ] Organizer verifies event-day settings and remaining student credit before opening registration.

Event-day restart: start `farmcraft-eval-02` and `farmcraft-eval-03` in `rg-farmcraft-evaluators-20261012`; verify all four `farmcraft-kr/id-01/02` worker slots idle in Admin → Workers & Devices, then open event gates from Admin. Do not start official Round 1 until the intended real participants and reference selection are checked.
