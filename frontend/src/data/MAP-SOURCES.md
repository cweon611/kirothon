# 여행지 뽑기 지도 출처

geoBoundaries / William & Mary geoLab, revision `9469f09`.

- 시군구: https://github.com/wmgeolab/geoBoundaries/blob/9469f09/releaseData/gbOpen/KOR/ADM2/geoBoundaries-KOR-ADM2_simplified.geojson
  - boundaryID: KOR-ADM2-91817680, reference year 2020
  - upstream sources: geoBoundaries, citypopulation.de
  - metadata license: Creative Commons Attribution 3.0 (https://creativecommons.org/licenses/by/3.0/)
- 시도 배경: https://github.com/wmgeolab/geoBoundaries/blob/9469f09/releaseData/gbOpen/KOR/ADM1/geoBoundaries-KOR-ADM1_simplified.geojson
  - metadata license: Public Domain

변경: 광주·전남만 필터, 좌표를 SVG 좌표로 투영, 소규모 섬 제거, 경계 단순화, 소수 첫째 자리 반올림, 색상 추가.
탐색용 약도이며 행정·측량 용도가 아니다. 영광군은 원본 ADM2에 없어 시도 배경 위에 근사 위치 표식을 사용한다.
지도 표식은 여행지역 선택용이며 특정 관광지나 방문 인증 위치를 나타내지 않는다.
새총의 실제 착지 지점에서 가장 가까운 여행지역을 선택한다. 혜택 API 연결 여부와 무관하게 광주·전남 27개 지역 모두 선택할 수 있다.

## 전체 여행지 선택 확장 (2026-10-30)

광주 5개 구·전남 22개 시군의 27개 대표점을 제공한다. 광산구 경계를 복원했다. 원본에 영광군 경계가 없어 대표점으로 선택하며 지도는 여행용 약도이다. 광주 구별 명칭은 다른 도시의 같은 구 이름과 좌표로 구분한다. 혜택 데이터 유무로 지역을 제외하지 않는다.
