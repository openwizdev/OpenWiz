# Launch post kit

Save one Markdown file per post. Put the TOML header between `+++` lines at the top, then write the publishable body in Markdown. Keep channel-specific copy such as a maker comment, prepared replies, captions or thread parts in the body under their own headings.

| Field | What to enter |
| --- | --- |
| `channel` | One of the nine values in the examples below. |
| `scheduled_pt` | Quoted `YYYY-MM-DD HH:MM`, using 24-hour Pacific Time (`America/Los_Angeles`). |
| `title` | The publishable title, or the product name on Product Hunt. |
| `tagline` | Product Hunt's required tagline, up to 60 characters. Omit elsewhere when unused. |
| Body | Publishable copy after the closing `+++`. |
| `links` | List of full HTTP(S) URLs, or `[]`. The same destination rules apply to inline links in the copy. |
| `media` | List of relative asset paths or permitted URLs, or `[]`. |
| `status` | Start with `draft`. Only the owner sets `approved` after review and `posted` after publishing. |
| `posted_link` | Use `""` until the owner posts, then record the published URL. |
| `claims` | List every release claim as a complete phrase appearing verbatim in both the publishable copy and the release changelog. Use `[]` for copy with zero release claims. The checker ignores whitespace differences. |
| `review_notes` | Optional quoted working notes, such as the community rules citation, disclosure needs or owner handoff. Review notes stay in the kit. |

Use OpenWiz's site (`openwiz.dev`), repositories under `github.com/openwizdev/`, or the destination channel's own site for publishable links. Keep direct requests for upvotes, GitHub stars and star trades out of every post file. Invite people to try the release or give specific feedback.

## Check a kit

```sh
python3 -I tools/launch/check_posts.py docs/launch/0.2.0 --changelog /path/to/release-changelog.md
python3 -I tools/launch/test_check_posts.py
```

Use Python 3.11 or later and a changelog file containing the target release's entry. The checker walks the folder and its subfolders for `.md` files beginning with `+++`. It leaves supporting Markdown without that header out of the check. It exits with `1` on refusals and prints each affected file and rule. It runs offline and reads files only.

Before setting `approved`, compare the title, body, tagline, captions and media against the changelog and confirm the claim list is complete. Review the links, the channel's current rules and any community-specific restrictions. The checker verifies the declared text against the changelog and looks for common engagement requests. Only the owner signs in, schedules, uploads or publishes.

## Channel rules

- **TikTok.** Use a vertical clip for the kit. Label realistic AI-generated video, audio and images, and review the clip for deceptive edits and fake engagement. [TikTok Community Guidelines](https://www.tiktok.com/community-guidelines/en/) and [AI-generated content rules](https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content)
- **YouTube Shorts.** Use a vertical clip of up to three minutes. Disclose realistic AI-generated or meaningfully altered content. [YouTube Community Guidelines](https://www.youtube.com/howyoutubeworks/policies/community-guidelines/), [Shorts eligibility](https://support.google.com/youtube/answer/15424877) and [AI disclosure rules](https://support.google.com/youtube/answer/14328491)
- **Show HN.** Begin the title with `Show HN:` and link to something readers can try. Share substantive work you helped build and stay for the discussion. The owner writes the final submission and replies in their own words, because HN bars generated submissions and generated or AI-edited comments. [Show HN Guidelines](https://news.ycombinator.com/showhn.html) and [Hacker News Guidelines](https://news.ycombinator.com/newsguidelines.html)
- **Product Hunt.** Use the product name and a descriptive tagline of up to 60 characters. Prepare a maker comment that invites feedback. Keep vote requests, rewards for votes and coordinated voting out. [Product Hunt Community Guidelines](https://help.producthunt.com/en/articles/3615694-community-guidelines), [launch form](https://help.producthunt.com/en/articles/17834537-4-build-your-product-page) and [promotion rules](https://help.producthunt.com/en/articles/17734384-5-how-to-promote-your-launch-and-what-to-avoid)
- **GitHub Trending.** Help readers try the project with a clear demo and getting-started instructions. Keep all engagement genuine and leave bought, traded and automated stars out of the launch. [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)
- **Reddit.** Check the destination subreddit's published rules for self-promotion, posting days and flair. Put its rules URL and how the draft follows it in `review_notes`. Skip communities that prohibit the post and avoid repeating the same promotion across communities. [Reddit Rules](https://redditinc.com/policies/reddit-rules) and [Reddit's community spam guidance](https://support.reddithelp.com/hc/en-us/articles/28012014962580-How-do-I-keep-spam-out-of-my-community)
- **Indie Hackers.** Share a build story that teaches something and asks a specific question. Keep the useful detail in the post and avoid link-only promotions or bulk outreach. [Indie Hackers Terms of Service](https://www.indiehackers.com/terms) and [posting guidance from the founder](https://www.indiehackers.com/post/how-do-you-make-a-successful-post-on-indie-hackers-f6745260fd)
- **DEV (dev.to).** Write a substantive developer article, check its commands, and follow DEV's disclosure and review guidance for AI-assisted text. [DEV Code of Conduct](https://dev.to/code-of-conduct) and [AI-assisted article guidelines](https://dev.to/guidelines-for-ai-assisted-articles-on-dev/)
- **X.** Give each thread part its own context. Avoid duplicate posts, unsolicited mass replies, irrelevant hashtags and coordinated engagement. [X Authenticity Policy](https://help.x.com/en/rules-and-policies/authenticity)

## Synthetic examples

These nine examples use an invented feature. To check them locally, save each block as its own `.md` file and pass a synthetic changelog containing `Adds a dry-run preview.`.

### TikTok

```markdown
+++
channel = "tiktok"
scheduled_pt = "2030-01-15 09:00"
title = "A preview before the run"
links = ["https://openwiz.dev/app/"]
media = ["video/synthetic-tiktok.mp4"]
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
Adds a dry-run preview. Here is the view before the run starts.
```

### YouTube Shorts

```markdown
+++
channel = "youtube-shorts"
scheduled_pt = "2030-01-15 09:00"
title = "What would happen if you ran it?"
links = ["https://openwiz.dev/app/"]
media = ["video/synthetic-short.mp4"]
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
Adds a dry-run preview. Watch the walkthrough and tell us where you would start.
```

### Show HN

```markdown
+++
channel = "show-hn"
scheduled_pt = "2030-01-15 08:00"
title = "Show HN: A dry-run preview demo"
links = ["https://github.com/openwizdev/OpenWiz"]
media = []
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
review_notes = "Synthetic form only. The owner writes the submission and first comment."
+++
Adds a dry-run preview. Try a run and tell me where the preview is unclear.
```

### Product Hunt

```markdown
+++
channel = "product-hunt"
scheduled_pt = "2030-01-15 00:01"
title = "OpenWiz"
tagline = "See the plan before you run it"
links = ["https://openwiz.dev/"]
media = ["gallery/synthetic-preview.png"]
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
Adds a dry-run preview. What else would you want to see before starting a run?
```

### GitHub Trending

```markdown
+++
channel = "github-trending"
scheduled_pt = "2030-01-15 09:30"
title = "Try the preview in OpenWiz"
links = ["https://github.com/openwizdev/OpenWiz"]
media = []
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
Adds a dry-run preview. See the getting-started instructions in the repository.
```

### Reddit

```markdown
+++
channel = "reddit"
scheduled_pt = "2030-01-15 10:00"
title = "How do you check a plan before starting a run?"
links = []
media = []
status = "draft"
posted_link = ""
claims = []
review_notes = "For an actual draft, cite the target subreddit's rules and record the allowed flair or posting window."
+++
What information do you check in a dry run before committing to the real thing?
```

### Indie Hackers

```markdown
+++
channel = "indie-hackers"
scheduled_pt = "2030-01-15 10:15"
title = "What do you put in a useful preview?"
links = []
media = []
status = "draft"
posted_link = ""
claims = []
+++
I started by sketching what happens when someone chooses to run a plan. What is the first thing you would add to that sketch?
```

### DEV

```markdown
+++
channel = "dev-to"
scheduled_pt = "2030-01-15 10:30"
title = "Read a dry-run plan in three steps"
links = ["https://github.com/openwizdev/OpenWiz"]
media = []
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
Adds a dry-run preview. Start with the target, trace the steps, then check which inputs each step uses.
```

### X

```markdown
+++
channel = "x"
scheduled_pt = "2030-01-15 10:45"
title = "A dry run in two posts"
links = ["https://openwiz.dev/app/"]
media = []
status = "draft"
posted_link = ""
claims = ["Adds a dry-run preview."]
+++
1. Adds a dry-run preview. Start by finding the target of the run.
2. Next, look at the proposed steps. Which one would you inspect first?
```
