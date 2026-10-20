/* 목업용 고정 데이터 — 실제 서비스에서는 공통 문장은 shared/data, 장소는 AI + 웹 검색 결과 */
'use strict';

/* 공통 상황 문장 30개 (FR-SENT-01) — countsTowardPlan: true 인 묶음만 센다. 30개에서 벗어나면 일정 계산식이 틀어진다(commons.test.js) */
const COMMON_SITUATIONS = [
  { key: 'airport', label: '공항·기내', countsTowardPlan: true, items: [
    { situation: '좌석 요청', en: 'Can I have a window seat, please?', ko: '창가 자리로 주시겠어요?',
      alt: [{ en: 'Could I get a window seat, if possible?', ko: '가능하면 창가 자리로 주실 수 있을까요?', label: '더 공손하게' }, { en: 'Window seat, please.', ko: '창가 자리요.', label: '짧게' }],
      talk: { nextFor: 1, replies: [{ en: 'Sure. Let me check what\'s available.', ko: '물론이죠. 가능한 좌석을 확인해 볼게요.', label: '가능한 경우' }, { en: 'Sorry, all the window seats are taken.', ko: '죄송하지만 창가 좌석이 모두 찼습니다.', label: '불가능한 경우' }], next: { en: 'That\'s okay. An aisle seat is fine.', ko: '괜찮습니다. 통로 자리도 좋아요.' } } },
    { situation: '탑승구 찾기', en: 'Where is my boarding gate?', ko: '제 탑승구가 어디예요?',
      alt: [{ en: 'Could you tell me where my gate is?', ko: '제 게이트가 어디인지 알려 주시겠어요?', label: '더 공손하게' }, { en: 'Which gate does this flight leave from?', ko: '이 비행기는 몇 번 게이트에서 출발해요?', label: '다르게 말하기' }],
      talk: { nextFor: 1, replies: [{ en: 'It\'s Gate 23. Go down this hall and it\'s on your right.', ko: '23번 게이트예요. 이 복도를 따라가면 오른쪽에 있어요.' }, { en: 'Can I see your boarding pass?', ko: '탑승권 좀 보여 주시겠어요?' }], next: { en: 'Here you go. Thank you.', ko: '여기 있어요. 감사합니다.' } } },
    { situation: '기내 요청', en: 'Could I get some water, please?', ko: '물 좀 주시겠어요?',
      alt: [{ en: 'Water, please.', ko: '물 주세요.', label: '짧게' }, { en: 'May I have a glass of water?', ko: '물 한 잔 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'Sure. Would you like some ice?', ko: '물론이죠. 얼음 넣어 드릴까요?' }, { en: 'I\'ll bring it right after the meal service.', ko: '식사 서비스가 끝나면 바로 가져다 드릴게요.' }], next: { en: 'No ice, please. Thank you.', ko: '얼음은 빼 주세요. 감사합니다.' } } },
    { situation: '기내식 선택', en: 'Chicken, please.', ko: '치킨으로 주세요.',
      alt: [{ en: 'I\'ll have the chicken, please.', ko: '치킨으로 할게요.', label: '더 공손하게' }, { en: 'The chicken, thank you.', ko: '치킨 주세요, 감사합니다.', label: '다르게 말하기' }],
      talk: { nextFor: 1, ask: { en: 'Would you like chicken or beef?', ko: '치킨과 소고기 중 어떤 걸로 드릴까요?' }, replies: [{ en: 'Here you are. Enjoy your meal.', ko: '여기 있습니다. 맛있게 드세요.', label: '있는 경우' }, { en: 'Sorry, we\'re out of chicken. Is beef okay?', ko: '죄송하지만 치킨이 다 떨어졌어요. 소고기 괜찮으세요?', label: '떨어진 경우' }], next: { en: 'Beef is fine, thank you.', ko: '소고기도 괜찮아요. 감사합니다.' } } },
    { situation: '수하물 찾기', en: 'Where can I pick up my baggage?', ko: '짐은 어디서 찾나요?',
      alt: [{ en: 'Where is the baggage claim?', ko: '수하물 찾는 곳이 어디예요?', label: '다르게 말하기' }, { en: 'Could you tell me where to get my bags?', ko: '짐 찾는 곳을 알려 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'Baggage claim is downstairs. Check the screen for your flight.', ko: '수하물 찾는 곳은 아래층이에요. 화면에서 항공편을 확인하세요.' }, { en: 'Your bags will come out on carousel 5.', ko: '짐은 5번 컨베이어 벨트로 나와요.' }], next: { en: 'Thanks. Is it this way?', ko: '감사합니다. 이쪽으로 가면 되나요?' } } },
  ]},
  { key: 'immigration', label: '입국심사', countsTowardPlan: true, items: [
    { situation: '방문 목적', en: "I'm here for sightseeing.", ko: '관광하러 왔어요.',
      alt: [{ en: 'Sightseeing.', ko: '관광이요.', label: '짧게' }, { en: 'I\'m here on vacation.', ko: '휴가로 왔어요.', label: '다르게 말하기' }],
      talk: { nextFor: 0, ask: { en: 'What\'s the purpose of your visit?', ko: '방문 목적이 무엇인가요?' }, replies: [{ en: 'How long will you be staying?', ko: '얼마나 머무르실 건가요?' }], next: { en: 'About a week.', ko: '일주일 정도요.' } } },
    { situation: '첫 방문', en: "It's my first visit.", ko: '처음 방문이에요.',
      alt: [{ en: 'This is my first time here.', ko: '여기 처음 와 봐요.', label: '다르게 말하기' }, { en: 'First time.', ko: '처음이에요.', label: '짧게' }],
      talk: { nextFor: 0, ask: { en: 'Have you been here before?', ko: '전에 와 보신 적 있나요?' }, replies: [{ en: 'Welcome. Enjoy your stay.', ko: '환영합니다. 즐거운 시간 보내세요.' }], next: { en: 'Thank you very much.', ko: '정말 감사합니다.' } } },
    { situation: '숙소 설명', en: "I'm staying at a hotel in the city.", ko: '시내 호텔에 묵어요.',
      alt: [{ en: 'I\'ll be staying at a hotel downtown.', ko: '시내 호텔에 머물 거예요.', label: '다르게 말하기' }, { en: 'At a hotel in the city.', ko: '시내 호텔이요.', label: '짧게' }],
      talk: { nextFor: 0, ask: { en: 'Where will you be staying?', ko: '어디에서 머무르시나요?' }, replies: [{ en: 'What\'s the name of the hotel?', ko: '호텔 이름이 뭔가요?' }], next: { en: 'Here is my hotel reservation.', ko: '여기 호텔 예약 확인서예요.' } } },
    { situation: '귀국 항공권', en: 'Here is my return ticket.', ko: '여기 귀국 항공권이에요.',
      alt: [{ en: 'This is my ticket back home.', ko: '이게 돌아가는 표예요.', label: '다르게 말하기' }, { en: 'Here you are. This is my return ticket.', ko: '여기요. 귀국 항공권이에요.', label: '더 공손하게' }],
      talk: { nextFor: 0, ask: { en: 'Do you have a return ticket?', ko: '귀국 항공권 있으세요?' }, replies: [{ en: 'Thank you. When do you fly back?', ko: '감사합니다. 언제 돌아가시나요?' }], next: { en: 'I fly back next Sunday.', ko: '다음 주 일요일에 돌아가요.' } } },
    { situation: '동행 여부', en: "I'm traveling alone.", ko: '혼자 여행 중이에요.',
      alt: [{ en: 'I\'m traveling by myself.', ko: '혼자 여행하고 있어요.', label: '다르게 말하기' }, { en: 'Just me.', ko: '저 혼자요.', label: '짧게' }],
      talk: { nextFor: 0, ask: { en: 'Are you traveling alone?', ko: '혼자 여행하시나요?' }, replies: [{ en: 'Okay. Do you have anything to declare?', ko: '알겠습니다. 신고할 물건 있으세요?' }], next: { en: 'No, nothing to declare.', ko: '아니요, 신고할 건 없어요.' } } },
  ]},
  { key: 'hotel', label: '숙소', countsTowardPlan: true, items: [
    { situation: '체크인', en: 'I have a reservation under [name].', ko: '[name] 이름으로 예약했어요.',
      alt: [{ en: 'I\'d like to check in. The name is [name].', ko: '체크인하려고요. 이름은 [name]이에요.', label: '더 공손하게' }, { en: 'Checking in, [name].', ko: '체크인이요, [name]입니다.', label: '짧게' }],
      talk: { nextFor: 0, ask: { en: 'Hi, how can I help you?', ko: '안녕하세요, 무엇을 도와드릴까요?' }, replies: [{ en: 'Thank you. May I see your passport?', ko: '감사합니다. 여권 보여 주시겠어요?', label: '찾은 경우' }, { en: 'Sorry, I can\'t find it. Could you spell your name?', ko: '죄송하지만 예약을 찾을 수 없네요. 성함 철자를 말씀해 주시겠어요?', label: '못 찾은 경우' }], next: { en: 'Sure, here you go.', ko: '네, 여기 있어요.' } } },
    { situation: '조식 시간', en: 'What time is breakfast?', ko: '조식은 몇 시예요?',
      alt: [{ en: 'When is breakfast served?', ko: '조식은 언제 나와요?', label: '다르게 말하기' }, { en: 'Could you tell me the breakfast hours?', ko: '조식 시간을 알려 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 1, replies: [{ en: 'It\'s from 7 to 10 a.m. on the first floor.', ko: '아침 7시부터 10시까지 1층에서요.' }, { en: 'Breakfast isn\'t included in your room rate.', ko: '객실 요금에 조식이 포함돼 있지 않아요.' }], next: { en: 'Can I add breakfast?', ko: '조식을 추가할 수 있나요?' } } },
    { situation: '와이파이', en: 'Could I get the Wi-Fi password?', ko: '와이파이 비밀번호 알려 주시겠어요?',
      alt: [{ en: 'What\'s the Wi-Fi password?', ko: '와이파이 비밀번호가 뭐예요?', label: '짧게' }, { en: 'Do you have the Wi-Fi password?', ko: '와이파이 비밀번호 있으세요?', label: '다르게 말하기' }],
      talk: { nextFor: 0, replies: [{ en: 'Sure. The network name and password are on this card.', ko: '네. 네트워크 이름과 비밀번호가 이 카드에 있어요.' }, { en: 'It\'s printed on your key card holder.', ko: '키 카드 홀더에 적혀 있어요.' }], next: { en: 'Thank you. It\'s working now.', ko: '감사합니다. 이제 연결돼요.' } } },
    { situation: '짐 보관', en: 'Can you keep my luggage until 3 p.m.?', ko: '오후 3시까지 짐 좀 맡아 주실 수 있나요?',
      alt: [{ en: 'Could I leave my bags here until 3 p.m.?', ko: '오후 3시까지 짐을 여기 둬도 될까요?', label: '더 공손하게' }, { en: 'Can I store my bags here?', ko: '짐을 맡길 수 있나요?', label: '다르게 말하기' }],
      talk: { nextFor: 0, replies: [{ en: 'Of course. Here\'s your claim tag.', ko: '물론이죠. 여기 보관표예요.', label: '가능한 경우' }, { en: 'Sorry, we can only keep it until noon.', ko: '죄송하지만 정오까지만 보관해 드릴 수 있어요.', label: '어려운 경우' }], next: { en: 'Thank you. I\'ll be back by three.', ko: '감사합니다. 3시까지 올게요.' } } },
    { situation: '체크아웃', en: "I'd like to check out, please.", ko: '체크아웃할게요.',
      alt: [{ en: 'Check out, please.', ko: '체크아웃이요.', label: '짧게' }, { en: 'I\'m checking out. Here is my key.', ko: '체크아웃할게요. 여기 열쇠요.', label: '다르게 말하기' }],
      talk: { nextFor: 0, replies: [{ en: 'Sure. Did you use anything from the minibar?', ko: '네. 미니바에서 드신 것 있으세요?' }, { en: 'Here\'s your bill. Please check it.', ko: '청구서예요. 확인해 주세요.' }], next: { en: 'No, I didn\'t. Can I get a receipt?', ko: '아니요. 영수증 받을 수 있을까요?' } } },
  ]},
  { key: 'transit', label: '대중교통', countsTowardPlan: true, items: [
    { situation: '길 찾기', en: 'How do I get to [destination]?', ko: '[destination]에 어떻게 가요?',
      alt: [{ en: 'Could you tell me the way to [destination]?', ko: '[destination] 가는 길을 알려 주시겠어요?', label: '더 공손하게' }, { en: 'Which way to [destination]?', ko: '[destination]은 어느 쪽이에요?', label: '짧게' }],
      talk: { nextFor: 0, replies: [{ en: 'Take the subway, Line 2, and get off at the third stop.', ko: '지하철 2호선을 타고 세 번째 역에서 내리세요.' }, { en: 'It\'s a ten-minute walk. Go straight and turn left.', ko: '걸어서 10분이에요. 직진하다가 왼쪽으로 도세요.' }], next: { en: 'Thank you. Is there a bus, too?', ko: '감사합니다. 버스도 있나요?' } } },
    { situation: '노선 묻기', en: 'Which line goes to [destination]?', ko: '[destination] 가는 노선이 뭐예요?',
      alt: [{ en: 'What train do I take to [destination]?', ko: '[destination]에 가려면 어떤 열차를 타요?', label: '다르게 말하기' }, { en: 'Could you tell me which line to take for [destination]?', ko: '[destination]에 가려면 몇 호선을 타야 하는지 알려 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'Take the green line toward Downtown.', ko: '다운타운 방면 초록 노선을 타세요.' }, { en: 'You need to transfer at Central Station.', ko: '중앙역에서 갈아타셔야 해요.' }], next: { en: 'How many stops is it?', ko: '몇 정거장이에요?' } } },
    { situation: '표 구매', en: 'One ticket, please.', ko: '표 한 장 주세요.',
      alt: [{ en: 'Can I get one ticket, please?', ko: '표 한 장 살 수 있을까요?', label: '더 공손하게' }, { en: 'One adult, please.', ko: '어른 한 명이요.', label: '다르게 말하기' }],
      talk: { nextFor: 0, replies: [{ en: 'One way or round trip?', ko: '편도요, 왕복이요?' }, { en: 'That\'s three dollars.', ko: '3달러예요.' }], next: { en: 'One way, please. Can I pay by card?', ko: '편도로 주세요. 카드로 낼 수 있나요?' } } },
    { situation: '정차 확인', en: 'Does this train stop at [destination]?', ko: '이 열차 [destination]에 서나요?',
      alt: [{ en: 'Is this the train to [destination]?', ko: '이게 [destination] 가는 열차예요?', label: '다르게 말하기' }, { en: 'Does this go to [destination]?', ko: '이거 [destination] 가요?', label: '짧게' }],
      talk: { nextFor: 0, replies: [{ en: 'Yes, it\'s the fourth stop.', ko: '네, 네 번째 역이에요.', label: '서는 경우' }, { en: 'No. Take the next train on the other side.', ko: '아니요. 반대편에서 다음 열차를 타세요.', label: '안 서는 경우' }], next: { en: 'Thanks. How long does it take?', ko: '감사합니다. 얼마나 걸려요?' } } },
    { situation: '하차 부탁', en: 'Please let me know when we get there.', ko: '도착하면 알려 주세요.',
      alt: [{ en: 'Could you tell me when to get off?', ko: '언제 내려야 하는지 알려 주시겠어요?', label: '더 공손하게' }, { en: 'Please tell me my stop.', ko: '제가 내릴 곳을 알려 주세요.', label: '다르게 말하기' }],
      talk: { nextFor: 0, replies: [{ en: 'Sure, I\'ll let you know.', ko: '네, 알려 드릴게요.' }, { en: 'It\'s three stops from here.', ko: '여기서 세 정거장이에요.' }], next: { en: 'Thank you so much.', ko: '정말 감사합니다.' } } },
  ]},
  { key: 'shopping', label: '길 묻기·쇼핑', countsTowardPlan: true, items: [
    { situation: '역 찾기', en: 'Excuse me, where is the nearest subway station?', ko: '실례지만, 가장 가까운 지하철역이 어디예요?',
      alt: [{ en: 'Is there a subway station near here?', ko: '근처에 지하철역이 있나요?', label: '다르게 말하기' }, { en: 'Excuse me, which way is the subway?', ko: '실례지만, 지하철은 어느 쪽이에요?', label: '짧게' }],
      talk: { nextFor: 0, replies: [{ en: 'Go straight two blocks. It\'s on your right.', ko: '두 블록 직진하세요. 오른쪽에 있어요.' }, { en: 'Sorry, I\'m not from around here.', ko: '죄송해요, 저도 이 동네 사람이 아니에요.' }], next: { en: 'Thank you for your help.', ko: '도와주셔서 감사합니다.' } } },
    { situation: '거리 묻기', en: 'Is it far from here?', ko: '여기서 멀어요?',
      alt: [{ en: 'How far is it from here?', ko: '여기서 얼마나 멀어요?', label: '다르게 말하기' }, { en: 'Is it within walking distance?', ko: '걸어갈 만한 거리예요?', label: '다르게 말하기' }],
      talk: { nextFor: 1, replies: [{ en: 'No, it\'s about five minutes on foot.', ko: '아니요, 걸어서 5분 정도예요.', label: '가까운 경우' }, { en: 'It\'s quite far. You\'d better take a taxi.', ko: '꽤 멀어요. 택시를 타시는 게 좋아요.', label: '먼 경우' }], next: { en: 'Where can I get a taxi?', ko: '택시는 어디서 타요?' } } },
    { situation: '가격 묻기', en: 'How much is this?', ko: '이거 얼마예요?',
      alt: [{ en: 'How much does this cost?', ko: '이건 가격이 얼마예요?', label: '다르게 말하기' }, { en: 'Could you tell me the price, please?', ko: '가격 좀 알려 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'It\'s 25 dollars.', ko: '25달러예요.' }, { en: 'It\'s on sale today, 20 percent off.', ko: '오늘 세일 중이라 20퍼센트 할인돼요.' }], next: { en: 'I\'ll take it. Can I pay by card?', ko: '이걸로 할게요. 카드로 낼 수 있나요?' } } },
    { situation: '사이즈', en: 'Do you have this in a smaller size?', ko: '이거 더 작은 사이즈 있어요?',
      alt: [{ en: 'Is there a smaller size?', ko: '더 작은 사이즈 있나요?', label: '짧게' }, { en: 'Could I try a smaller size, please?', ko: '더 작은 사이즈로 입어 볼 수 있을까요?', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'Let me check in the back.', ko: '창고에서 확인해 볼게요.', label: '확인해 줄 때' }, { en: 'Sorry, that\'s the smallest size we have.', ko: '죄송하지만 그게 가장 작은 사이즈예요.', label: '없는 경우' }], next: { en: 'Can I try it on?', ko: '입어 봐도 될까요?' } } },
    { situation: '영수증', en: 'Can I get a receipt, please?', ko: '영수증 주시겠어요?',
      alt: [{ en: 'Receipt, please.', ko: '영수증이요.', label: '짧게' }, { en: 'Could I have a receipt, please?', ko: '영수증 받을 수 있을까요?', label: '더 공손하게' }],
      talk: { nextFor: 1, replies: [{ en: 'Sure. Here you go.', ko: '네, 여기 있어요.' }, { en: 'Would you like it printed or emailed?', ko: '출력해 드릴까요, 이메일로 보내 드릴까요?' }], next: { en: 'Printed, please. Thank you.', ko: '출력해 주세요. 감사합니다.' } } },
  ]},
  { key: 'emergency', label: '돌발 상황', countsTowardPlan: true, items: [
    { situation: '분실', en: 'I lost my passport. Can you help me?', ko: '여권을 잃어버렸어요. 도와주시겠어요?',
      alt: [{ en: 'I can\'t find my passport. Please help me.', ko: '여권을 못 찾겠어요. 도와주세요.', label: '다르게 말하기' }, { en: 'My passport is missing.', ko: '여권이 없어졌어요.', label: '짧게' }],
      talk: { nextFor: 0, replies: [{ en: 'Where did you last see it?', ko: '마지막으로 어디서 보셨어요?' }, { en: 'You should contact your embassy.', ko: '대사관에 연락하셔야 해요.' }], next: { en: 'I think I left it in a taxi.', ko: '택시에 두고 내린 것 같아요.' } } },
    { situation: '신고', en: 'Please call the police.', ko: '경찰 좀 불러 주세요.',
      alt: [{ en: 'Could you call the police, please?', ko: '경찰 좀 불러 주시겠어요?', label: '더 공손하게' }, { en: 'Call the police!', ko: '경찰 불러 주세요!', label: '짧게' }],
      talk: { nextFor: 1, replies: [{ en: 'Okay. Are you hurt?', ko: '알겠어요. 다치셨어요?' }, { en: 'What happened?', ko: '무슨 일이에요?' }], next: { en: 'Someone stole my bag.', ko: '누가 제 가방을 훔쳐 갔어요.' } } },
    { situation: '진료', en: 'I need to see a doctor.', ko: '의사한테 진료받아야 해요.',
      alt: [{ en: 'I need a doctor.', ko: '의사가 필요해요.', label: '짧게' }, { en: "I'd like to see a doctor, please.", ko: '진료를 받고 싶어요.', label: '더 공손하게' }],
      talk: { nextFor: 0, replies: [{ en: 'What are your symptoms?', ko: '어떤 증상이 있으세요?' }, { en: 'There\'s a clinic around the corner.', ko: '모퉁이에 병원이 있어요.' }], next: { en: 'I have a fever and a headache.', ko: '열이 나고 머리가 아파요.' } } },
    { situation: '약국', en: 'Where is the nearest pharmacy?', ko: '가장 가까운 약국이 어디예요?',
      alt: [{ en: 'Is there a pharmacy near here?', ko: '근처에 약국이 있나요?', label: '다르게 말하기' }, { en: 'Could you tell me where a pharmacy is?', ko: '약국이 어디 있는지 알려 주시겠어요?', label: '더 공손하게' }],
      talk: { nextFor: 1, replies: [{ en: 'There\'s one across the street.', ko: '길 건너편에 있어요.' }, { en: 'It\'s closed now. Try the 24-hour one near the station.', ko: '지금은 문을 닫았어요. 역 근처 24시간 약국에 가 보세요.' }], next: { en: 'Which way is the station?', ko: '역은 어느 쪽이에요?' } } },
    { situation: '천천히', en: 'Can you speak more slowly, please?', ko: '좀 더 천천히 말해 주시겠어요?',
      alt: [{ en: 'Sorry, could you say that again?', ko: '죄송하지만 다시 말해 주시겠어요?', label: '다르게 말하기' }, { en: 'Slowly, please.', ko: '천천히요.', label: '짧게' }],
      talk: { nextFor: 1, replies: [{ en: 'Of course. Sorry about that.', ko: '물론이죠. 죄송해요.' }, { en: 'Sure. Would you like me to write it down?', ko: '네. 적어 드릴까요?' }], next: { en: 'Yes, please. Thank you.', ko: '네, 부탁해요. 감사합니다.' } } },
  ]},
  /* 참고용 — 날짜별 학습량(위 30개, app.js R.counts 의 C)에 넣지 않는다. 문장 모음·카드로 연습에서만 보인다.
     사용자 테스트 설문 자유응답(10/18): 같이 있는 사람이 응급일 때 영어로 전화 문의(당직병원·응급실)가 어렵다.
     안전 문장이라 AI 생성이 아닌 검수된 고정 문장이다(agent_contract/README.md 1절). 도움 요청·장소 찾기만 — 응급처치·약 안내는 넣지 않는다. */
  { key: 'emergency_call', label: '응급 전화', countsTowardPlan: false, items: [
    { situation: '구급차 요청', en: 'Please call an ambulance.', ko: '구급차 좀 불러 주세요.' },
    { situation: '동행이 아플 때', en: 'My friend is sick.', ko: '친구가 아파요.' },
    { situation: '전화로 응급실 찾기', en: 'Where is the nearest emergency room?', ko: '가장 가까운 응급실이 어디예요?' },
    { situation: '전화로 야간 진료 찾기', en: 'Is there a hospital open now?', ko: '지금 문 연 병원 있나요?' },
  ]},
];

/* 장소별 문장 템플릿 — 실제로는 AI-03이 생성. 맛집 첫 문장은 반드시 대표 메뉴 주문 */
const PLACE_TEMPLATES = {
  restaurant: [
    { situation: '대표 메뉴 주문', en: "I'd like the {menuEn}, please.", ko: '{menuKo} 주세요.' },
    { situation: '입장', en: 'A table for two, please.', ko: '두 명 자리 부탁해요.' },
    { situation: '추천 묻기', en: 'What do you recommend?', ko: '추천 메뉴가 뭐예요?' },
    { situation: '포장', en: 'Can I get this to go?', ko: '포장해 주시겠어요?' },
    { situation: '계산', en: 'Can I have the check, please?', ko: '계산서 주시겠어요?' },
    { situation: '결제', en: 'Can I pay by card?', ko: '카드로 계산할 수 있나요?' },
    { situation: '대기', en: 'How long is the wait?', ko: '얼마나 기다려야 해요?' },
    { situation: '추가 요청', en: 'Could I get some napkins?', ko: '냅킨 좀 주시겠어요?' },
    { situation: '알레르기', en: "I'm allergic to nuts.", ko: '견과류 알레르기가 있어요.' },
    { situation: '인사', en: 'It was delicious, thank you!', ko: '정말 맛있었어요, 감사합니다!' },
  ],
  attraction: [
    { situation: '찾아가기', en: 'How do I get to {en}?', ko: '{name}에 어떻게 가요?' },
    { situation: '티켓 구매', en: 'Two tickets, please.', ko: '표 두 장 주세요.' },
    { situation: '운영 시간', en: 'What time does it close?', ko: '몇 시에 닫아요?' },
    { situation: '입구', en: 'Where is the entrance?', ko: '입구가 어디예요?' },
    { situation: '사진 부탁', en: 'Could you take a picture of us?', ko: '저희 사진 좀 찍어 주시겠어요?' },
    { situation: '가이드 투어', en: 'Is there a guided tour?', ko: '가이드 투어가 있나요?' },
    { situation: '화장실', en: 'Where is the restroom?', ko: '화장실이 어디예요?' },
    { situation: '소요 시간', en: 'How long does it take to see everything?', ko: '다 둘러보는 데 얼마나 걸려요?' },
    { situation: '소지품', en: 'Can I bring this bag inside?', ko: '이 가방 들고 들어가도 되나요?' },
    { situation: '출구', en: 'Which way is the exit?', ko: '출구는 어느 쪽이에요?' },
  ],
};

const SRC_NY = [{ title: 'NYC Tourism + Conventions', url: 'https://www.nyctourism.com/' }];
const SRC_BOS = [{ title: 'Meet Boston', url: 'https://www.meetboston.com/' }];

/* 웹 검색 결과를 흉내 낸 장소 풀 (AI-01) */
const PLACE_POOLS = {
  '뉴욕': {
    attr: [
      { name: '자유의 여신상', en: 'the Statue of Liberty', area: '로어 맨해튼', desc: '리버티섬에 서 있는 뉴욕의 상징. 배터리 파크에서 페리를 타요.', reason: '처음 뉴욕에 온다면 꼭 봐야 할 랜드마크', sources: SRC_NY },
      { name: '브루클린 브리지', en: 'the Brooklyn Bridge', area: '로어 맨해튼', desc: '맨해튼과 브루클린을 잇는 보행자 다리.', reason: '해 질 녘 스카이라인 산책 명소', sources: SRC_NY },
      { name: '센트럴파크', en: 'Central Park', area: '미드타운', desc: '맨해튼 한가운데 있는 거대한 도시 공원.', reason: '자전거로 여유롭게 둘러보기 좋음', sources: SRC_NY },
      { name: '타임스스퀘어', en: 'Times Square', area: '미드타운', desc: '전광판과 브로드웨이 극장이 모인 광장.', reason: '밤에 가장 뉴욕다운 풍경', sources: SRC_NY },
      { name: '메트로폴리탄 미술관', en: 'the Met', area: '어퍼 이스트 사이드', desc: '세계 3대 미술관 중 하나. 이집트관이 유명해요.', reason: '비 오는 날에도 하루를 보낼 수 있음', sources: SRC_NY },
      { name: '하이라인', en: 'the High Line', area: '첼시', desc: '옛 고가 철도를 공원으로 바꾼 산책로.', reason: '첼시 마켓과 함께 둘러보기 좋음', sources: SRC_NY },
      { name: '엠파이어 스테이트 빌딩', en: 'the Empire State Building', area: '미드타운', desc: '86층 전망대에서 보는 맨해튼 야경.', reason: '고전적인 뉴욕 전망', sources: SRC_NY },
    ],
    rest: [
      { name: "Joe's Pizza", area: '그리니치 빌리지', cuisine: '피자', menuEn: 'cheese slice', menuKo: '치즈 슬라이스', desc: '1975년부터 이어온 뉴욕 스타일 피자 가게.', reason: '줄 서도 금방 빠지는 뉴욕 대표 조각 피자', sources: SRC_NY },
      { name: "Katz's Delicatessen", area: '로어 이스트 사이드', cuisine: '델리', menuEn: 'pastrami sandwich', menuKo: '파스트라미 샌드위치', desc: '1888년에 문을 연 유대식 델리.', reason: '두툼한 파스트라미가 상징인 곳', sources: SRC_NY },
      { name: 'Los Tacos No.1', area: '첼시', cuisine: '타코', menuEn: 'adobada taco', menuKo: '아도바다 타코', desc: '첼시 마켓 안의 멕시칸 타코 스탠드.', reason: '하이라인 산책 전후로 들르기 좋음', sources: SRC_NY },
      { name: 'Shake Shack', area: '플랫아이언', cuisine: '버거', menuEn: 'ShackBurger', menuKo: '쉑버거', desc: '매디슨 스퀘어 파크에서 시작한 버거 가게.', reason: '1호점의 공원 분위기', sources: SRC_NY },
      { name: 'Ess-a-Bagel', area: '미드타운', cuisine: '베이글', menuEn: 'everything bagel with cream cheese', menuKo: '크림치즈 에브리싱 베이글', desc: '손으로 굴려 만드는 큼직한 베이글.', reason: '뉴욕식 아침 식사 체험', sources: SRC_NY },
      { name: 'Levain Bakery', area: '어퍼 웨스트 사이드', cuisine: '베이커리', menuEn: 'chocolate chip walnut cookie', menuKo: '초콜릿 칩 호두 쿠키', desc: '두툼한 쿠키로 유명한 베이커리.', reason: '센트럴파크 산책 간식', sources: [] },
      { name: "Xi'an Famous Foods", area: '차이나타운', cuisine: '중식', menuEn: 'spicy cumin lamb noodles', menuKo: '쯔란 양고기 비앙비앙면', desc: '시안식 손국수 전문점.', reason: '매콤한 맛이 그리울 때', sources: SRC_NY },
    ],
  },
  '보스턴': {
    attr: [
      { name: '프리덤 트레일', en: 'the Freedom Trail', area: '다운타운', desc: '미국 독립 역사 유적 16곳을 잇는 4km 산책로.', reason: '보스턴 역사를 한 번에', sources: SRC_BOS },
      { name: '퀸시 마켓', en: 'Quincy Market', area: '다운타운', desc: '19세기 시장 건물을 살린 푸드홀과 상점가.', reason: '이동일에 가볍게 둘러보기 좋음', sources: SRC_BOS },
      { name: '보스턴 커먼', en: 'Boston Common', area: '다운타운', desc: '미국에서 가장 오래된 공원.', reason: '프리덤 트레일의 출발점', sources: SRC_BOS },
      { name: '하버드 대학교', en: 'Harvard University', area: '케임브리지', desc: '하버드 야드와 서점가를 걸어 보는 캠퍼스 투어.', reason: '지하철 레드라인으로 쉽게 이동', sources: SRC_BOS },
      { name: '펜웨이 파크', en: 'Fenway Park', area: '펜웨이', desc: '1912년에 개장한 레드삭스 홈구장.', reason: '경기가 없는 날에도 투어 가능', sources: SRC_BOS },
      { name: '보스턴 미술관', en: 'the Museum of Fine Arts', area: '펜웨이', desc: '인상파 컬렉션이 풍부한 대형 미술관.', reason: '펜웨이 파크와 가까움', sources: SRC_BOS },
    ],
    rest: [
      { name: 'Neptune Oyster', area: '노스 엔드', cuisine: '해산물', menuEn: 'lobster roll', menuKo: '랍스터 롤', desc: '작은 오이스터 바. 버터 랍스터 롤이 유명해요.', reason: '보스턴에서 가장 유명한 랍스터 롤', sources: SRC_BOS },
      { name: "Mike's Pastry", area: '노스 엔드', cuisine: '디저트', menuEn: 'cannoli', menuKo: '카놀리', desc: '이탈리아 이민자 거리의 페이스트리 가게.', reason: '노스 엔드 산책 필수 코스', sources: SRC_BOS },
      { name: 'Union Oyster House', area: '다운타운', cuisine: '해산물', menuEn: 'clam chowder', menuKo: '클램 차우더', desc: '1826년에 문을 연, 미국에서 가장 오래된 레스토랑 중 하나.', reason: '뉴잉글랜드식 차우더의 원조', sources: SRC_BOS },
      { name: "Giacomo's", area: '노스 엔드', cuisine: '이탈리안', menuEn: 'lobster fra diavolo', menuKo: '랍스터 프라 디아볼로', desc: '줄 서서 먹는 작은 이탈리안 식당.', reason: '해산물 파스타 맛집', sources: SRC_BOS },
      { name: 'Legal Sea Foods', area: '시포트', cuisine: '해산물', menuEn: 'fried clams', menuKo: '조개 튀김', desc: '보스턴에서 시작한 해산물 체인.', reason: '하버 뷰와 함께', sources: SRC_BOS },
      { name: 'Row 34', area: '포트 포인트', cuisine: '오이스터 바', menuEn: 'oysters on the half shell', menuKo: '생굴', desc: '현지 굴을 다양하게 맛볼 수 있는 곳.', reason: '굴 종류를 비교해 먹는 재미', sources: SRC_BOS },
    ],
  },
};

/* 목록에 없는 도시는 일반 이름으로 채움 (검색 결과가 부족한 경우 확인용으로 8곳만 제공) */
function genericPool(city) {
  const areas = ['중심가', '구시가지', '강변', '항구 지구'];
  const attrNames = [['구시가지', 'the Old Town'], ['중앙 광장', 'the Central Square'], ['시립 박물관', 'the City Museum'], ['전망대', 'the Observatory'], ['강변 산책로', 'the Riverside Walk'], ['중앙 시장', 'the Central Market'], ['대성당', 'the Cathedral'], ['식물원', 'the Botanical Garden']];
  const restNames = [['Local Kitchen', '로컬 정식', 'house special'], ['Market Bistro', '시장 비스트로', 'daily plate'], ['Harbor Grill', '해산물 구이', 'grilled fish'], ['Old Town Cafe', '카페 브런치', 'brunch set'], ['Noodle House', '면 요리', 'signature noodles'], ['Corner Bakery', '베이커리', 'butter croissant'], ['Street Food Hall', '길거리 음식', 'street skewer'], ['Family Diner', '가정식', 'home-style stew']];
  return {
    attr: attrNames.map(([ko, en], i) => ({ name: `${city} ${ko}`, en, area: areas[i % 4], desc: `${city}의 대표 명소 중 하나예요.`, reason: '여행자 후기가 많은 곳', sources: [] })),
    rest: restNames.map(([en, cuisine, menu], i) => ({ name: `${en} ${city}`, area: areas[(i + 1) % 4], cuisine, menuEn: menu, menuKo: menu, desc: `${city} 현지인이 자주 찾는 식당.`, reason: '대표 메뉴가 확실한 곳', sources: [] })),
  };
}

/* 관리자 화면용 가짜 운영 데이터 (stageAt 기반 지표 계산에 사용) */
const MOCK_TRIPS = [
  { id: 'tr_8f21', user: 'minji.k', route: '일본 · 오사카', status: 'studying', reached: 4, reportSec: 48, requests: 3, fails: 0, completion: null, failStreak: 0, regen: 1 },
  { id: 'tr_7c02', user: 'jh.park', route: '미국 · 뉴욕 → 보스턴', status: 'studying', reached: 4, reportSec: 71, requests: 3, fails: 0, completion: 0.82, failStreak: 0, regen: 0 },
  { id: 'tr_6a9e', user: 'sora.lee', route: '영국 · 런던', status: 'report_generating', reached: 1, reportSec: null, requests: 1, fails: 0, completion: null, failStreak: 0, regen: 0, genMinAgo: 2 },
  { id: 'tr_5d13', user: 'doyun', route: '프랑스 · 파리 → 니스', status: 'route_generating', reached: 2, reportSec: 88, requests: 2, fails: 0, completion: null, failStreak: 0, regen: 2, genMinAgo: 23 },
  { id: 'tr_4b77', user: 'yerin.c', route: '호주 · 시드니', status: 'report_failed', reached: 1, reportSec: null, requests: 3, fails: 3, completion: null, failStreak: 3, regen: 0 },
  { id: 'tr_3e40', user: 'hyun.w', route: '태국 · 방콕', status: 'studying', reached: 4, reportSec: 55, requests: 3, fails: 1, completion: 0.41, failStreak: 0, regen: 0 },
  { id: 'tr_2f88', user: 'eunji', route: '스페인 · 바르셀로나', status: 'report_done', reached: 2, reportSec: 96, requests: 1, fails: 0, completion: null, failStreak: 0, regen: 0 },
  { id: 'tr_1a05', user: 'taeho', route: '미국 · 샌프란시스코', status: 'studying', reached: 4, reportSec: 62, requests: 4, fails: 1, completion: 0.67, failStreak: 0, regen: 1 },
  { id: 'tr_0c61', user: 'nari.s', route: '캐나다 · 밴쿠버', status: 'input_done', reached: 0, reportSec: null, requests: 0, fails: 0, completion: null, failStreak: 0, regen: 0 },
  { id: 'tr_9d32', user: 'jiwoo', route: '싱가포르', status: 'sentences_failed', reached: 3, reportSec: 39, requests: 3, fails: 1, completion: null, failStreak: 1, regen: 0 },
  { id: 'tr_8e14', user: 'minho.y', route: '이탈리아 · 로마 → 피렌체', status: 'studying', reached: 4, reportSec: 83, requests: 3, fails: 0, completion: 0.29, failStreak: 0, regen: 3 },
  { id: 'tr_7b58', user: 'seoyeon', route: '베트남 · 다낭', status: 'studying', reached: 4, reportSec: 44, requests: 3, fails: 0, completion: 0.58, failStreak: 0, regen: 0 },
];

const MOCK_USERS = [
  { email: 'minji.k@gmail.com', name: '김민지', trips: [{ route: '일본 · 오사카', state: '학습 중' }, { route: '대만 · 타이베이', state: '보관' }] },
  { email: 'jh.park@gmail.com', name: '박지훈', trips: [{ route: '미국 · 뉴욕 → 보스턴', state: '종료' }] },
  { email: 'sora.lee@gmail.com', name: '이소라', trips: [{ route: '영국 · 런던', state: '보고서 생성 중' }] },
  { email: 'doyun@gmail.com', name: '정도윤', trips: [{ route: '프랑스 · 파리 → 니스', state: '방문 순서 생성 중' }, { route: '일본 · 도쿄', state: '보관' }, { route: '홍콩', state: '보관' }] },
  { email: 'yerin.c@gmail.com', name: '최예린', trips: [{ route: '호주 · 시드니', state: '보고서 실패' }] },
];

/* 빈 화면 방지용 데모 학습 기록. 실제 사용자 학습에서 생긴 기억이 아니다 (demo:true 로 표시). */
const DEMO_WEAK = [
  { category_id: 'restaurant', id: 'allergy_notice', situation: '알레르기·재료 고지', en: 'I have a peanut allergy. Does this contain peanuts?', ko: '땅콩 알레르기가 있어요. 이거에 땅콩이 들어가나요?', demo: true },
];
