FARMCRAFT 50-TEAM REHEARSAL — GO DIRECTLY TO ROUND 1

What is included
  Start-50-Team-Test.ps1 (adds new menu 9 / -Mode Round1Fast)
  Quick-Round1.ps1 (new: special launch, reads live server first)
  FarmCraft_50_Full_Rehearsal/rehearsal.py (adds --allow-unverified-wave2 to official ONLY)
  FarmCraft_50_Full_Rehearsal/round1_fast_precheck.py (new, read-only checks)
  FarmCraft_50_Full_Rehearsal/test_round1_fast_mock.py (three offline tests)

Nothing in this ZIP replaces runtime/, sessions/, teams.csv, bots/, saved jobs, or backup files.
It does not modify the server, database, or reference bots until you explicitly approve
new official participant submissions, AFTER opening qualification yourself in Admin.

INSTRUCTIONS (PowerShell)
1. Keep your original runtime/ folder. Stop other rehearsal scripts. Extract ZIP at
   D:\kaggriculture\Kaggriculture with -Force.
2. Admin Control Center: verify exact five selected references, qualification settings,
   then manually START ROUND 1 (QUALIFICATION_OPEN).
   Do not close/finalize Round 1 or change any reference bots before QA submissions.
3. Launch:
   cd D:\kaggriculture\Kaggriculture
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-50-Team-Test.ps1
   Choose 9 (Round 1 skip wave2)
   OR:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-50-Team-Test.ps1 -Mode Round1Fast
4. This read-only precheck verifies 50/50 wave-1 completed AND 50/50 replay checks,
   validates temp + five original refs, checks existing official jobs, and waits for
   all 49 already submitted wave-2 jobs to finish without failure. It DOES NOT
   invent the missing FC26_R50_045 sandbox-2 result. Check that no QA sandbox job
   is still queued or running. Any inconsistency stops the script BEFORE official POSTs.
5. Check all 50 team sessions (explicitly approve recovery only if actually expired).
6. Confirm exactly: SUBMIT ROUND1 SKIP WAVE2
   This sends up to 50 real, one-attempt official QA submissions (not temp).
   On any ambiguous HTTP failure, DO NOT rerun or resubmit until job IDs are
   reconciled using admin job history.
7. Once all 50 IDs confirmed, optionally monitor Round 1. You still manually
   submit team temp if desired. Finalize qualification and start Round 2 manually.

The normal menu 4 keeps STRICT two-wave requirements. Menu 3 MUST NOT be rerun.
Wave 2 remains 49 confirmed/1 missing; this patch waives it for one permitted QA
Round 1 only. It does not erase, mark completed, or repeat any sandbox job.
No UI/playback 10x or tournament performance is validated by this waiver.

Offline checks:
  py -3 .\FarmCraft_50_Full_Rehearsal\test_round1_fast_mock.py -v
  These mock tests have passed. Live submission was NOT performed by the author.
