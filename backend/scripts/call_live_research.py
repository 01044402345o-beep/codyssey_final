"""라이브 서버 도쿄 실호출 측정 스크립트"""
import json
import time
import urllib.request

BASE_URL = "https://codyssey-final.onrender.com"

def call_research(cities_info, label):
    req_body = {
        "countries": [{"name": "Japan"}],
        "cities": cities_info
    }
    data = json.dumps(req_body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    
    print(f"\n==========================================")
    print(f"[{label}] Request: {req_body['cities'][0]['name']} ({req_body['cities'][0]['start']} ~ {req_body['cities'][0]['end']})")
    print(f"==========================================")
    
    t0 = time.time()
    req = urllib.request.Request(f"{BASE_URL}/research", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Submit failed: {e}")
        return
        
    print(f"Submit response: status={res.get('status')}, job_id={res.get('job_id')}, cached={res.get('cached')}")
    
    if res.get("status") == "done":
        dur = time.time() - t0
        report = res.get("report", {})
        cities = report.get("cities", [])
        city0 = cities[0] if cities else {}
        extract = city0.get("extract") or {}
        places = city0.get("places") or []
        ko_count = sum(1 for p in places if p.get("summary_ko"))
        print(f"Instant cache done! duration={dur:.2f}s")
        print(f"extract.status={extract.get('status')}, places={len(places)}, places_with_summary_ko={ko_count}")
        return res
        
    jid = res.get("job_id")
    if not jid:
        print("No job_id returned.")
        return res
        
    while True:
        time.sleep(3)
        poll_req = urllib.request.Request(f"{BASE_URL}/research/{jid}")
        try:
            with urllib.request.urlopen(poll_req, timeout=15) as resp:
                poll = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"Poll warning: {e}")
            continue
            
        elapsed = time.time() - t0
        status = poll.get("status")
        print(f"[{elapsed:5.1f}s] status={status}")
        
        if status != "running":
            report = poll.get("report", {})
            cities = report.get("cities", [])
            city0 = cities[0] if cities else {}
            extract = city0.get("extract") or {}
            places = city0.get("places") or []
            ko_count = sum(1 for p in places if p.get("summary_ko"))
            
            print(f"\nFinished in {elapsed:.2f}s!")
            print(f"Report quality: {report.get('quality')}")
            print(f"City 0: {city0.get('key')}, resolved={city0.get('resolved')}")
            print(f"Extract status: {extract.get('status')}")
            print(f"Places total: {len(places)}")
            print(f"Places with summary_ko (Korean summary): {ko_count}")
            if ko_count > 0:
                print(f"Sample summary_ko: {places[0].get('name')} -> {places[0].get('summary_ko')}")
            return poll

if __name__ == "__main__":
    # 1회차: 도쿄 2026-11-20 ~ 2026-11-23
    call_research([{"name": "Tokyo", "start": "2026-11-20", "end": "2026-11-23", "ci": 0}], "Call 1: Tokyo 2026-11-20~23")
    
    # 2회차: 같은 날짜 도쿄 2026-11-20 ~ 2026-11-23 (연속 2회차)
    call_research([{"name": "Tokyo", "start": "2026-11-20", "end": "2026-11-23", "ci": 0}], "Call 2: Tokyo 2026-11-20~23 (Same date)")
    
    # 3회차: 날짜 변경 (다른 달 2026-12-05 ~ 2026-12-08)
    call_research([{"name": "Tokyo", "start": "2026-12-05", "end": "2026-12-08", "ci": 0}], "Call 3: Tokyo 2026-12-05~08 (Different month)")
