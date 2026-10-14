# OpenCode coverage sandbox의 Docker CPU 용량 결속

## 실제 실패

공개 target `.github#2617@b3983b467c2d7f1440b5024acb6a3860eb3e043d`의 중앙 run `38443671498`, coverage job `115456508271`은 `orgmetra-ci-01` / group 13에서 실행됐다. 공개 exact source 확보와 tool image build는 성공했다. 이후 고정 `--cpus 4`가 CPU 2개인 Docker daemon에서 거부됐다. sandbox exit 125로 출력 파일이 생성되지 않았고 테스트·coverage 측정·모델 추론은 실행되지 않았다. diagnostic `COMMENTED` 리뷰는 정식 승인으로 인정하지 않는다.

## 좁은 수리와 검증

Docker daemon의 기존 `docker info --format '{{.NCPU}}'` 결과를 양의 정수로 검증한다. sandbox CPU limit는 `min(4, NCPU)`로 설정한다. 조회 실패·빈 값·0·부호·소수·줄 삽입은 실행 전 거부한다. host의 `nproc`를 daemon 용량으로 대체하지 않는다.

메모리 14g, PID limit, network none, capability set, mount, 출력 인증, cleanup 및 100% coverage 기준은 변경하지 않는다. CPU 수리를 메모리 적합성이나 실제 runner 실행의 성공으로 주장하지 않는다. 원래 실행은 고정 workflow source를 유지하므로 수리 소스를 소비하는 fresh 지원 경로가 별도로 필요하다. 새 dispatch나 reviewer identity 우회는 이 소스 수리에 포함하지 않는다.

실제 YAML의 launch shell을 추출하고 synthetic Docker CLI만 치환하여 argv를 검증한다. 첫 harness는 동일 cleanup 문자열의 첫 위치를 잘못 선택해 실패했다. 위치를 바로잡은 후 원래 `4 != 2` assertion 실패를 관측했고, 최소 수리 후 CPU/거부 입력 15개가 통과했다. 이는 실제 Docker daemon이나 Actions 실행의 검증은 아니다.

## 공식 문서

- Docker. (2026). *docker system info*. https://docs.docker.com/reference/cli/docker/system/info/
- Docker. (2026). *Resource constraints*. https://docs.docker.com/engine/containers/resource_constraints/

부모의 실제 문서 조회는 첫 구현 및 15개 GREEN 이후인 2026-10-14에 수행했다. 이를 구현 전 조회로 소급하지 않는다. `--cpus`는 container CPU 사용의 상한이며 테스트 수나 정확성 기준을 바꾸는 옵션이 아니다.
