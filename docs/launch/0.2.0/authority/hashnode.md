# Hashnode crosspost of the dev.to article

Status: draft. Nothing has been posted. This is a note for the owner to approve. An agent opened no Hashnode account, signed in nowhere and published nothing.

Destination: Hashnode (hashnode.com), on a blog the owner already runs or chooses for OpenWiz. The crosspost republishes the launch spike's dev.to article (LS6 of #3865, drafted in `docs/launch/0.2.0/dev-to.md`). It is not a new article.

## Rules, read 2026-11-28

- Hashnode's own guide [Why you should republish your devblog posts and how to do it](https://townhall.hashnode.com/why-you-should-republish-your-devblog-posts-and-how-to-do-it) says Hashnode lets a writer add the original URL to a republished post. Hashnode then sets the canonical tag to it, so search engines treat the original as the source.
- Hashnode's help article [How to set a canonical link](https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link) gives the steps. Open the publish panel, find Are you republishing?, choose Add Original URL and paste the original article's address. The help site's address did not resolve for an automated reader on 2026-11-28, so these labels come from its indexed copy. The owner confirms them in the editor.
- Hashnode's [Terms of Use](https://hashnode.com/terms) govern the post itself. The owner reads them before publishing.
- The dev.to side follows the channel rules in the [launch kit](../../README.md#channel-rules): the [DEV Code of Conduct](https://dev.to/code-of-conduct) and the [AI-assisted article guidelines](https://dev.to/guidelines-for-ai-assisted-articles-on-dev/). The crosspost keeps the same disclosure.

## The crosspost

- **Order:** publish on dev.to first. Crosspost only after the dev.to article is live and its public URL is recorded in `posted_link` in `docs/launch/0.2.0/dev-to.md`.
- **Canonical URL:** the dev.to article's public URL, exactly as recorded in `posted_link`. Hashnode's own URL is never the canonical one.
- **Title:** the dev.to article's title, unchanged.
- **Subtitle:** OpenWiz, the open source agent factory
- **Body:** the dev.to article's body, unchanged, including its commands and their notes. Change no claim. Every claim stays one that the 0.2.0 changelog makes.
- **Opening line, above the body:** This article first appeared on DEV. The original is linked as this post's canonical source.
- **Disclosure:** keep the dev.to article's note on AI-assisted writing word for word.
- **Tags (up to five):** open-source, ai, developer-tools, github, rust
- **Cover image:** the same cover as the dev.to article, if it has one
- **Links in the body:** only openwiz.dev, repositories under github.com/openwizdev/ and the dev.to original
- **Closing line:** Try OpenWiz from https://openwiz.dev/, and tell us on GitHub what was unclear: https://github.com/openwizdev/OpenWiz/issues

Ask nobody for likes, reactions, follows or stars, on either site.

## Owner checklist

- The dev.to article is live and its link is recorded.
- In the Hashnode editor, paste the body and set Add Original URL to that link before publishing.
- After publishing, open the post's page source. Check that its canonical link is the dev.to URL.
- Record the Hashnode post's URL in a follow-up pull request.
