## Security Learnings
* `shopt nocasematch`를 사용할 때 서브쉘이나 루프를 통한 부수 효과가 남아있지 않도록 항상 이전 설정을 안전하게 저장하고 복구하는 패턴(`shopt -q` 활용)을 적용해야 함.
* `eval`과 같은 불안전한 명령어 실행을 지양하고, 대신 안전한 조건문(`if [ "$was_nocasematch" -eq 0 ]`)을 사용하여 쉘 옵션을 제어해야 보안 취약점을 예방할 수 있음.
