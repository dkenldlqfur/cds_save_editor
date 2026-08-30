# 대항해시대 3 세이브 에디터

[![최신 Release](https://img.shields.io/github/v/release/dkenldlqfur/cds_save_editor?label=Release)](https://github.com/dkenldlqfur/cds_save_editor/releases/latest)

`대항해시대 3`의 세이브 파일(`.CDS`, `.SAV`)을 열어 주인공, 인물, 함대, 도시, 아이템, 발견물 및 이벤트 플래그를 편집하는 Windows용 도구입니다.

최신 배포본은 [GitHub Releases](https://github.com/dkenldlqfur/cds_save_editor/releases/latest)에서 받을 수 있습니다.

## 주요 기능

- **주인공 정보**
  - 이름, 국적, 생일, 현재 날짜, 직업, 혈액형, 얼굴
  - 능력치, 생명력, 소지금·저금·계약금, 기술, 언어, 명성·악명
  - 스폰서 계약과 남은 일수 확인·해제
- **인물 정보**
  - 부관·항해사·측량사·통역 등 역할 배정 인물 조회와 해제·되돌리기
  - 기본 정보, 능력치, 명성, 기술, 언어 조회
  - 배우자와 운명의 반려자 판정, 여급 웹 도감
- **함대 및 도시**
  - 보유 함선 추가·제거·편집, 기함·선원·추진력·내구도·대포·마스트 설정
  - 도시 기본 정보, 보유 시설, 시장·조선소, 교역 정보 편집
- **아이템과 발견물**
  - 아이템 도감, 소지품·보관함 이동 및 추가·삭제
  - 발견물 진행 상태(미등장·미발견·발견·보고 완료), 힌트 상태, 발견·보고 일자 편집
  - 이미지·동영상 리소스가 있을 때 상세 창에서 표시 또는 재생
- **이벤트 플래그**
  - 세이브의 이벤트 플래그 조회·편집
- **편의 기능**
  - 기존 파일 저장 시 시간표시 백업 생성
  - 창 크기 조절과 Windows DPI 변경 대응
  - 배포 EXE에서 GitHub Release 기반 업데이트 확인·설치

## 사용 방법

1. 게임을 종료합니다.
2. `CDS_SaveEditor.exe`를 실행합니다.
3. **세이브 파일 열기**로 `.CDS` 또는 `.SAV` 파일을 엽니다.
4. 원하는 값을 수정한 뒤 **세이브 데이터 저장**을 누릅니다.

기존 파일을 덮어쓸 때 **저장 시 시간표시 백업 파일 자동 생성**을 켜 두면, 같은 폴더에 `파일명_YYYYMMDD_HHMMSS.CDS` 형식의 백업을 만듭니다.

## 소스에서 실행하기

개발 환경은 Windows와 Python 3.14를 기준으로 구성했습니다.

```powershell
py -3 -m pip install pillow python-vlc pyinstaller
py -3 CDS_SaveEditor.pyw
```

`Resources` 폴더는 실행에 필요한 JSON, 이미지, 동영상, VLC 런타임과 Tcl/Tk 리소스를 포함하므로 소스 파일과 함께 유지해야 합니다.

## 배포 빌드

프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
py -3 -m PyInstaller --noconfirm --clean CDS3_SaveEditor.spec
```

생성된 실행 파일은 `dist` 폴더에 만들어집니다. 배포 ZIP에는 `CDS_SaveEditor.exe`만 포함하며, 프로그램이 필요한 리소스를 단일 실행 파일에 묶습니다.

## 주의 사항

- 편집 전 원본 세이브 파일을 별도로 보관하세요.
- 게임이 세이브 파일을 사용 중인 상태에서는 저장하지 마세요.
- 일부 값은 게임 내부의 조건·이벤트·최대치에 의해 로드 후 조정될 수 있습니다.
- 이 도구는 비공식 팬 프로젝트이며, 게임 및 원본 리소스의 권리는 해당 권리자에게 있습니다.

## 프로젝트 구성

```text
CDS_SaveEditor.pyw       메인 에디터
CDS3_SaveEditor.spec     PyInstaller 배포 설정
editor_core/             세이브 레코드 처리 모듈
Resources/data/          JSON 데이터와 설정
Resources/barmaids.html  여급 웹 도감
Resources/               이미지·동영상·VLC·Tcl/Tk 등 실행 리소스
```
