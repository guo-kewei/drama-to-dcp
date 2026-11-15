"""生成合成测试短剧（用于 M1 端到端验证）。

用法:
    python tests/make_test_media.py [输出目录]
默认输出到 E:\AI\短剧转电影自动化平台\tests\media\
生成:
    测试A_16x9/  3 集 1920×1080 30fps 立体声正弦音（应推荐 Flat）
    测试B_scope/ 2 集 2560×1080 30fps（应推荐 Scope）
    测试C_坏集/  3 集其中 1 集为损坏文件（验证坏集跳过）
"""
import sys
from pathlib import Path

MEDIA_ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(__file__).resolve().parent / "media"


def ffmpeg() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.core.config import PROJECT_ROOT
    from app.tools.ffmpeg import FFmpeg
    return str(FFmpeg.discover(None, PROJECT_ROOT).ffmpeg)


def make_episode(ff: str, out: Path, w: int, h: int, secs: int,
                 freq: int, ep: int) -> None:
    """测试视频：移动彩条+计时文字+双声道正弦音。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"testsrc2=size={w}x{h}:rate=30:duration={secs},"
          f"drawtext=text='EP{ep}':fontsize={h//8}:fontcolor=white:"
          f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5")
    import subprocess
    r = subprocess.run(
        [ff, "-y", "-f", "lavfi", "-i", vf,
         "-f", "lavfi", "-i",
         f"sine=frequency={freq}:sample_rate=48000:duration={secs}",
         "-f", "lavfi", "-i",
         f"sine=frequency={freq+200}:sample_rate=48000:duration={secs}",
         "-filter_complex", "[1:a][2:a]amerge=inputs=2,pan=stereo|c0=c0|c1=c1[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def main() -> None:
    ff = ffmpeg()
    print(f"FFmpeg: {ff}")
    print(f"输出目录: {MEDIA_ROOT}")

    a = MEDIA_ROOT / "测试A_16x9"
    for i, (sec, freq) in enumerate([(8, 440), (7, 494), (9, 523)], 1):
        p = a / f"第{i:02d}集.mp4"
        make_episode(ff, p, 1920, 1080, sec, freq, i)
        print(f"  {p.name} {sec}s")

    b = MEDIA_ROOT / "测试B_scope"
    for i, (sec, freq) in enumerate([(8, 440), (8, 494)], 1):
        p = b / f"ep{i:02d}.mp4"
        make_episode(ff, p, 2560, 1080, sec, freq, i)
        print(f"  {p.name} {sec}s")

    c = MEDIA_ROOT / "测试C_坏集"
    for i, sec in enumerate([(6, ), (6, ), (6, )], 1):
        p = c / f"ep{i:02d}.mp4"
        make_episode(ff, p, 1920, 1080, sec[0], 440, i)
    (c / "ep99.mp4").write_bytes(b"this is not a video file")
    print("  测试C_坏集 含 1 个损坏文件")
    print("完成。")


if __name__ == "__main__":
    main()
