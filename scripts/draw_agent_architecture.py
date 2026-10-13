"""README의 설명용 구조도를 만듭니다. LangSmith 캡처와 구분합니다."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    image = Image.new('RGB', (1440, 1160), 'white')
    draw = ImageDraw.Draw(image)
    regular = ROOT / 'assets/NanumGothic-Regular.ttf'
    bold = ROOT / 'assets/NanumGothic-Bold.ttf'
    title = ImageFont.truetype(str(bold), 34)
    font = ImageFont.truetype(str(regular), 23)
    small = ImageFont.truetype(str(regular), 20)
    color = '#1F2937'
    draw.text((70, 45), 'Physical AI 투자 검토 · Orchestrator-Workers', font=title, fill=color)
    draw.text((70, 100), '설명용 구조도 | 실제 실행 증거는 tracing-*.png와 실행 기록에 별도 보관', font=small, fill='#555555')

    def box(rect, heading, detail, fill='#F3F4F6'):
        draw.rounded_rectangle(rect, radius=16, fill=fill, outline=color, width=2)
        x, y, right, bottom = rect
        draw.text(((x + right) / 2, y + 25), heading, font=font, fill=color, anchor='mm')
        draw.text(((x + right) / 2, y + 60), detail, font=small, fill=color, anchor='mm')

    def arrow(points, label='', label_xy=None):
        draw.line(points, fill=color, width=3, joint='curve')
        x, y = points[-1]
        px, py = points[-2]
        angle = math.atan2(y - py, x - px)
        head = [(x, y)] + [(x - 13 * math.cos(angle + sign * .5), y - 13 * math.sin(angle + sign * .5)) for sign in (-1, 1)]
        draw.polygon(head, fill=color)
        if label and label_xy:
            draw.text(label_xy, label, font=small, fill=color)

    box((470, 160, 970, 250), 'Orchestrator · planner', '요청과 기업 → 질문·관점·완료 조건 계획')
    arrow([(720, 250), (720, 310)], '계획의 작업 수만큼 Send', (765, 272))
    box((360, 310, 1080, 405), 'Research Workers · task 1 … N', 'RAG 검색·원문 의미 검수 | 최대 3개 동시 실행', '#EAF2F8')
    draw.text((60, 334), '164쪽 원문', font=font, fill=color)
    draw.text((60, 369), 'BGE-M3 + FAISS', font=small, fill=color)
    arrow([(235, 356), (360, 356)])
    arrow([(720, 405), (720, 465)])
    box((470, 465, 970, 555), 'Reducer · 결과 병합', 'task_id별 최신 revision 한 개 보관')
    arrow([(720, 555), (720, 615)])
    box((470, 615, 970, 705), 'Synthesizer · 보고서 작성', '관점별 근거 선택·확인 조건으로 정리')
    arrow([(720, 705), (720, 765)])
    box((470, 765, 970, 855), 'Judge + Gate · 품질 평가와 분기', '근거성 · 중립성 · 편향 · 네 관점', '#EAF2F8')
    arrow([(470, 810), (275, 810), (275, 357), (360, 357)], 'research: 해당 작업 재조사', (35, 455))
    arrow([(970, 810), (1180, 810), (1180, 660), (970, 660)], 'rewrite: 보고서 수정', (995, 710))
    arrow([(720, 855), (720, 935)], 'approve 또는 한도·오류 fallback', (765, 887))
    box((410, 935, 1030, 1025), '결과 저장 · 종료', '통과 여부와 미확인을 구분한 Markdown / PDF')
    draw.text((70, 1070), '복구: SQLite checkpoint  |  관측: LangSmith + events.jsonl  |  연결: trace_id', font=small, fill=color)
    draw.text((70, 1110), '한도: 작업 20개 · 수정 기본 2회 · 제어 단계 16 · recursion 60 · 실행별 API 비용 상한', font=small, fill=color)
    destination = ROOT / 'submission/architecture.png'
    destination.parent.mkdir(exist_ok=True)
    image.save(destination)
    print(destination)


if __name__ == '__main__':
    main()
