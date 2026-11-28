import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).with_name("check_posts.py")
FORM = CHECKER.parents[2] / "docs/launch/README.md"
CLAIM = "Adds a dry-run preview."
CHANNELS = {
    "tiktok", "youtube-shorts", "show-hn", "product-hunt", "github-trending",
    "reddit", "indie-hackers", "dev-to", "x",
}


def post(body=CLAIM, **overrides):
    fields = {
        "channel": "show-hn",
        "scheduled_pt": "2030-01-15 08:00",
        "title": "Show HN: A synthetic demo",
        "links": ["https://openwiz.dev/app/"],
        "media": [],
        "status": "draft",
        "posted_link": "",
        "claims": [CLAIM],
        **overrides,
    }
    metadata = "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items())
    return f"+++\n{metadata}\n+++\n\n{body}\n"


class LaunchPostTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.changelog = self.root / "changelog.md"
        self.changelog.write_text(f"## Synthetic release\n\n- {CLAIM}\n", encoding="utf-8")
        self.posts = self.root / "posts"
        self.posts.mkdir()

    def write(self, name, content):
        path = self.posts / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def check(self):
        return subprocess.run(
            [sys.executable, "-I", str(CHECKER), str(self.posts), "--changelog", str(self.changelog)],
            capture_output=True, text=True, check=False,
        )

    def assert_accepted(self, content):
        self.write("post.md", content)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_refused(self, content, rule):
        self.write("post.md", content)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"post.md: {rule}:", result.stderr)

    def test_show_hn_title(self):
        self.assert_accepted(post())
        for title in ("A synthetic demo", "Show HN - A synthetic demo", "show hn: A synthetic demo"):
            with self.subTest(title=title):
                self.assert_refused(post(title=title), "show-hn-title")

    def test_product_hunt_tagline_at_and_over_60(self):
        fields = {"channel": "product-hunt", "title": "Synthetic demo"}
        self.assert_accepted(post(tagline="x" * 60, **fields))
        self.assert_refused(post(tagline="x" * 61, **fields), "product-hunt-tagline")
        self.assert_refused(post(**fields), "product-hunt-tagline")

    def test_engagement_requests(self):
        self.assert_accepted(post(f"{CLAIM} GitHub stars are one way people bookmark projects. Feedback is welcome."))
        cases = (
            ("upvote-request", "Please **upvote** our launch."),
            ("upvote-request", "A few upvotes would help us."),
            ("upvote-request", "Would you vote for us?"),
            ("star-request", "If this helped, star the repo."),
            ("star-request", "Please leave us a GitHub star."),
            ("star-request", "Drop us a ⭐ on GitHub."),
            ("star-trade", "Star-for-star, anyone?"),
            ("star-trade", "I'll star yours if you star ours."),
            ("star-trade", "Let's trade stars."),
        )
        for rule, copy in cases:
            with self.subTest(copy=copy):
                self.assert_refused(post(f"{CLAIM} {copy}"), rule)
        self.assert_refused(post(title="Show HN: Please upvote us"), "upvote-request")
        self.assert_refused(
            post(channel="product-hunt", title="Synthetic demo", tagline="Give us a star"), "star-request"
        )

    def test_only_project_and_current_channel_link_destinations(self):
        self.assert_accepted(post(
            f"{CLAIM}\n\n[Try the demo](https://openwiz.dev/app/) or see [the HN thread][hn].\n"
            "\n[hn]: https://news.ycombinator.com/item?id=123",
            links=["https://github.com/openwizdev/OpenWiz", "https://github.com/openwizdev/WizSkills"],
            media=["video/synthetic.mp4"],
        ))
        for url in (
            "https://openwiz.dev.example.com/", "https://github.com/other/project",
            "https://github.com/openwizdev/OpenWiz/%2e%2e/%2e%2e/other/project",
            "https://openwiz.dev@elsewhere.example/", "https://www.reddit.com/r/example/",
            "javascript:alert(1)", "//other.example/path",
        ):
            with self.subTest(url=url):
                self.assert_refused(post(links=[url]), "link-destination")
        self.assert_refused(post(f"{CLAIM} [Demo](https://elsewhere.example/)"), "link-destination")
        self.assert_refused(post(f"{CLAIM}\n\n[demo]: https://elsewhere.example/"), "link-destination")
        self.assert_refused(post(f"{CLAIM} <https://elsewhere.example/>"), "link-destination")
        self.assert_refused(post(f"{CLAIM} See www.elsewhere.example."), "link-destination")
        self.assert_refused(post(f"{CLAIM} See elsewhere.example/path."), "link-destination")
        self.assert_refused(post(f"{CLAIM} [Demo](/unresolved)"), "link-destination")
        self.assert_refused(post(title="Show HN: https://elsewhere.example/"), "link-destination")
        self.assert_refused(post(media=["https://elsewhere.example/demo.mp4"]), "link-destination")
        self.assert_refused(post(status="posted", posted_link="https://elsewhere.example/"), "link-destination")
        self.assert_accepted(post(f"{CLAIM} Read `README.md` at openwiz.dev."))

    def test_changelog_must_support_each_declared_claim_in_the_copy(self):
        self.assert_accepted(post(f"[Demo](https://openwiz.dev/)\n\n{CLAIM}"))
        self.assert_accepted(post("What would make this useful?", claims=[]))
        invented = "Finishes every build in one second."
        self.assert_refused(post(f"{CLAIM} {invented}", claims=[CLAIM, invented]), "changelog-claim")
        self.assert_refused(post("Adds a live preview.", claims=[CLAIM]), "changelog-claim")
        self.changelog.write_text("## Synthetic release\n\n- Removes the old preview.\n", encoding="utf-8")
        self.assert_refused(post(), "changelog-claim")

    def test_posted_status_requires_link(self):
        self.assert_accepted(post(status="approved"))
        self.assert_accepted(post(status="posted", posted_link="https://news.ycombinator.com/item?id=123"))
        self.assert_refused(post(status="posted"), "posted-link")
        self.assert_refused(post(status="posted", posted_link=" "), "posted-link")
        self.assert_refused(post(status="scheduled"), "post-form")

    def test_folder_reports_each_refused_file_and_each_rule(self):
        self.write("valid.md", post())
        self.write("a.md", post(title="Missing prefix", status="posted"))
        self.write("video/b.md", post(f"{CLAIM} Please upvote!", links=["https://elsewhere.example"]))
        self.write("video/c.md", "+++\nchannel = [\n+++\n")
        self.write("cut-list.md", "# Supporting notes, outside the post form\n")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([line.split(": ", 2)[:2] for line in result.stderr.splitlines()], [
            ["a.md", "show-hn-title"], ["a.md", "posted-link"],
            ["video/b.md", "upvote-request"], ["video/b.md", "link-destination"],
            ["video/c.md", "post-form"],
        ])
        self.assertEqual(result.stdout, "")

    def test_bad_inputs_fail_closed(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no post files", result.stderr)
        self.assert_refused(post(scheduled_pt="2030-02-31 25:00"), "post-form")
        self.assert_refused(post().replace('claims = ["Adds a dry-run preview."]\n', ""), "post-form")
        self.changelog.unlink()
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("changelog.md: changelog-input:", result.stderr)

    def test_documented_form_and_examples(self):
        self.assertTrue(FORM.is_file(), "the form and channel examples must be documented")
        form = FORM.read_text(encoding="utf-8")
        self.assertIn("Only the owner", form)
        examples = re.findall(r"^```markdown\n(\+\+\+\n.*?)^```$", form, flags=re.M | re.S)
        self.assertCountEqual(
            [re.search(r'^channel = "([^"\n]+)"$', example, flags=re.M)[1] for example in examples],
            CHANNELS,
        )
        for i, example in enumerate(examples):
            self.write(f"example-{i}.md", example)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Checked 9 launch post(s).\n")


if __name__ == "__main__":
    unittest.main()
