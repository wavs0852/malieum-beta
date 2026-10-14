### 도커 기본 명령어 (참고용)

컨테이너 실행 제어 및 접속
```bash
docker run [옵션] 이미지_이름 # 컨테이너 생성 및 실행
docker stop 컨테이너_이름_또는_ID # 컨테이너 중지
docker start 컨테이너_이름_또는_ID # 중지된 컨테이너 다시 시작
docker rm 컨테이너_이름_또는_ID # 중지된 컨테이너 완전 삭제
docker exec -it 컨테이너_이름_또는_ID /bin/bash # 실행 중인 컨테이너 내부 터미널 접속
```

컨테이너 상태 확인 및 모니터링
```bash
docker ps # 실행 중인 컨테이너 목록 확인
docker ps -a # 종료된 컨테이너를 포함한 모든 목록 확인
docker logs 컨테이너_이름_또는_ID # 컨테이너 내부 로그 확인
docker stats # 컨테이너 자원 사용량 실시간 확인
```

**TIP: 내부 파일 조작시 VS Code의 Dev Containers 확장을 쓰면 매우 편함**

<br>

# Redis 컨테이너 이용 방법

### 컨테이너 종료 및 삭제 (수정이 필요하거나 문제가 있을 경우 사용)
```bash
docker stop malieum-redis # 중지
docker rm malieum-redis # 삭제
```

### 컨테이너 시작 (컨테이너 종료>삭제 이후에 처음부터 실행할 경우 사용)
 - 반드시 해당 README 파일이 존재하는 경로에서 실행할 것 ($PWD 때문)
```bash
docker run -d \
  --name malieum-redis \
  -p 6380:6379 \
  -v "$PWD/data:/data" \
  --restart always \
  redis:latest redis-server --appendonly yes
```