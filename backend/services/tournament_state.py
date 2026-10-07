from __future__ import annotations
import math

ACTIVE_TOURNAMENT=("starting","round_running","next_round","final")

def initial_state(players: list[str] | None=None) -> dict:
    players=sorted(players or [],key=str.lower)
    return {"status":"registration","message":"Registration is open. Waiting for players to join.","playersCount":len(players),"maxPlayers":100,"registeredPlayers":players,"currentRound":0,"totalRoundsEstimate":math.ceil(math.log2(len(players))) if len(players)>1 else 0,"currentMatches":[],"roundsHistory":[],"byes":[],"eliminatedPlayers":[],"allMatches":[],"champion":None,"finalScore":None,"error":None,"isLive":False,"selectedQualifiers":[]}

def apply_progress(state: dict,event: str,data: dict) -> dict:
    if event=="ROUND_START":
        n=data["round"];state.update(status="final" if data.get("isFinal") else "round_running",currentRound=n,currentMatches=data["matches"],message=f"Round {n} in progress")
        if data.get("byePlayer"):state["byes"].append({"round":n,"player":data["byePlayer"]})
    elif event=="MATCH_START":
        i=data["matchIndex"]
        if i<len(state["currentMatches"]):state["currentMatches"][i]["status"]="running"
        state["message"]=f"Round {data['round']}: {data['player1']} vs {data['player2']} playing..."
    elif event=="MATCH_END":
        i=data["matchIndex"]
        if i<len(state["currentMatches"]):state["currentMatches"][i].update({k:data.get(k) for k in ("p1Score","p2Score","winner","loser","tieReplays","seed")}|{"status":"completed"})
        if not any(x["player"]==data["loser"] for x in state["eliminatedPlayers"]):state["eliminatedPlayers"].append({"player":data["loser"],"eliminatedInRound":data["round"],"eliminatedBy":data["winner"]})
        state["allMatches"].append(data);state["message"]=f"{data['winner']} defeated {data['loser']}"
    elif event=="ROUND_END":
        n=data["round"]
        if not any(x["round"]==n for x in state["roundsHistory"]):state["roundsHistory"].append({"round":n,"matches":[dict(x) for x in state["currentMatches"]],"byePlayer":next((b["player"] for b in state["byes"] if b["round"]==n),None),"advancing":data["advancing"]})
        if data.get("remainingCount",0)>1:state.update(status="next_round",message=f"Round {n} completed.")
    elif event=="TOURNAMENT_END":
        champion=data["champion"];state.update(status="champion",champion=champion,isLive=False,message=f"Tournament Complete! Champion: {champion['username']}")
        if data.get("finalMatch"):
            f=data["finalMatch"];state["finalScore"]={k:f[k] for k in ("player1","player2","p1Score","p2Score","winner")}
    elif event=="TOURNAMENT_ERROR":state.update(status="error",error=data["error"],isLive=False,message=f"Tournament aborted: {data['error']}")
    return state
