# Noema document-reader npm SemVer 보안 floor

## 관측

`tests/test_noema_document_reader_dependency_security.py`는 npm `package-lock.json`의 `fast-uri`와 `ip-address` 버전을 Python PEP 440 `packaging.version.Version`으로 비교했다. 이 비교는 npm SemVer와 prerelease 표기가 다르다.

고정된 부모 source `b2f1ab72788639aaf8389228606e9d70217336de`에서 `_locked_versions()`를 직접 실행하면 `3.1.8-1`은 `3.1.8.post1`으로 정규화되어 final security floor `3.1.8` 이상으로 허용됐다. 설치된 npm bundled semver 7.8.5는 같은 문자열을 유효한 numeric prerelease로 인식하고 final보다 낮게 판정했다. `3.1.8-beta.1`은 양쪽에서 낮고 `3.1.8`은 양쪽에서 final이다. 이 기록은 실제 lock에 취약한 prerelease가 있다는 주장이나 exploit 증거가 아니다.

## 결정

외부 Python version parser 또는 npm binary에 의존하지 않고, 테스트 파일 안에 strict npm SemVer parser를 둔다. parser는 `major.minor.patch`, prerelease identifier의 numeric-vs-string 우선순위, build metadata 무시, malformed value 거부를 구현한다. 이 검사는 document-reader package-lock 보안 floor 계약의 test oracle이며 runtime code가 아니다.

## 검증

RED는 `3.1.8-1 < 3.1.8`을 요구했으나 기존 PEP 440 helper가 이를 반대로 처리해 실패했다. GREEN은 numeric prerelease, named prerelease, build metadata, malformed version, nested vulnerable dependency 및 현재 lock floor를 포함한 focused 11 tests와 docstring 100%다.

현재 branch·hosted check·독립 approval 수용은 별도다. 부모 수정은 ordinary merge로 child stack에만 보존했고 원격 부모 branch를 직접 갱신하지 않았다.
