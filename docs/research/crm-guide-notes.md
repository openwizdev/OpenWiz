# CRM guide notes

Research for the agent-native CRM draft in [docs/specs/agent-native-crm.md](../specs/agent-native-crm.md). The notes were taken from the public pages linked below. The printed book was not in hand. Ampersand's public preview is a seven-part field guide, presented as volume one, for engineers who build software and agents that read from and write to CRMs. The preview's own description is "A field guide for engineers building software and AI agents that read from and write to CRMs." A shorter request-a-copy page carries the foreword and the same table of contents.

The guide's installation diagram says its counts are illustrative, not measured customer data. Those counts are not repeated here as facts.

## Sources

- Preview: <https://www.ampersand.ai/resources/engineers-guide-to-crms>
- Request-a-copy page, foreword by Ayan Barua, contents: <https://www.ampersand.ai/engineers-guide-to-crms>
- Ampersand Salesforce connector: <https://docs.ampersand.ai/provider-guides/salesforce>
- Ampersand subscribe actions: <https://docs.ampersand.ai/subscribe-actions>
- Subscribe Actions launch post, 8 May 2025: <https://www.ampersand.ai/blog/subscribe-actions-bringing-real-time-crm-events-and-actions-to-life>
- Salesforce objects and fields: <https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_concepts.htm>
- Salesforce custom fields: <https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/custom_fields.htm>
- Salesforce describe global: <https://developer.salesforce.com/docs/platform/api-rest/guide/resources-describeglobal.html>
- Salesforce sObject describe: <https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_describe.htm>
- Salesforce API request limits: <https://developer.salesforce.com/docs/atlas.en-us.salesforce_app_limits_cheatsheet.meta/salesforce_app_limits_cheatsheet/salesforce_app_limits_platform_api.htm>
- Salesforce Bulk API limits: <https://developer.salesforce.com/docs/atlas.en-us.salesforce_app_limits_cheatsheet.meta/salesforce_app_limits_cheatsheet/salesforce_app_limits_platform_bulkapi.htm>
- Salesforce Change Data Capture allocations: <https://developer.salesforce.com/docs/atlas.en-us.change_data_capture.meta/change_data_capture/cdc_allocations.htm>
- HubSpot CRM model: <https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm>
- HubSpot object APIs: <https://developers.hubspot.com/docs/api-reference/latest/crm/using-object-apis>
- HubSpot search: <https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm>
- HubSpot associations: <https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide>
- HubSpot webhooks: <https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide>
- HubSpot usage limits: <https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines>
- Twenty data model: <https://docs.twenty.com/getting-started/core-concepts/data-model>
- Twenty APIs: <https://docs.twenty.com/developers/extend/api>
- Attio objects and lists: <https://docs.attio.com/docs/objects-and-lists>
- Attio standard objects: <https://docs.attio.com/docs/standard-objects/standard-objects>
- Attio people: <https://docs.attio.com/docs/standard-objects/standard-objects-people>
- Attio companies: <https://docs.attio.com/docs/standard-objects/standard-objects-companies>
- Attio deals: <https://docs.attio.com/docs/standard-objects/standard-objects-deals>
- Folk custom fields: <https://developer.folk.app/core-concepts/custom-fields>
- Folk custom objects: <https://developer.folk.app/core-concepts/custom-objects>
- Pipedrive custom fields: <https://pipedrive.readme.io/docs/core-api-concepts-custom-fields>
- Pipedrive API v2 custom fields: <https://pipedrive.readme.io/docs/pipedrive-api-v2-migration-guide>
- Pipedrive rate limiting: <https://pipedrive.readme.io/docs/core-api-concepts-rate-limiting>
- Close overview: <https://developer.close.com/api/overview>
- Close rate limits: <https://developer.close.com/api/overview/rate-limits>

Launch posts confirm the book exists and state the problem in the authors' words. They are not a substitute for the preview: [Dion Low](https://www.linkedin.com/posts/dionlow_last-week-we-launched-the-book-i-wrote-activity-7516561502812766208-BYfw), [Ampersand](https://www.linkedin.com/posts/withampersand_last-week-we-announced-our-15m-series-a-activity-7516234269929775104-w-Z6). The preview credits Dion Low as primary author, with Anusha Talasila, Jaehyun (Jay) Lim and Joel Theodros.

## What the guide says a CRM is

A CRM turns interactions into linked records so sales, marketing, customer success and leadership can ask different questions of one set of records. Sales asks what to do next on a deal. Marketing asks which campaigns produce engagement. Customer success asks whether an account is healthy. Leadership asks how the pipeline is doing. The guide's account-executive interview describes the salesperson's loop as prospecting, qualifying, pitching and closing, and says management, marketing and customer success use the same records for forecast, source and renewal.

A spreadsheet works for a few people and breaks as columns and editors multiply: conflicting edits, weak permissions, manual reminders, fragile links, slow queries, and history scattered across tabs. The guide maps those to locking, access control, workflows, referential integrity, indexing and retained history. A CRM supplies the mechanisms. It does not decide the business rules.

The core map in the preview:

| Business concept | Salesforce | HubSpot |
| --- | --- | --- |
| Organization | Account | Company |
| Person | Contact | Contact |
| Potential sale | Opportunity | Deal |
| Support issue | Case | Ticket |

Activities are records too. The preview says Salesforce models tasks and calendar events as Task and Event, and that their links depend on the activity. Custom objects are how a business names what the standard model does not: a listing, a job posting, an inventory item. Custom fields such as `Renewal_Tier__c` carry that customer's own words. Two Salesforce customers do not share a schema.

The guide's engineering consequences:

- Discover objects, fields and relationships at runtime, then confirm what they mean before mapping them. A fixed set of endpoints is the wrong expectation.
- Application schemas change by review and migration. A customer CRM changes when sales, marketing or customer success adds a step. Oversight varies. Old fields stay because an old report still uses them (`Stage__c` beside `Stage_v2__c` is the preview's example).
- Reading one record is not enough. An agent reconstructs context by walking the graph: person, company, deals, conversations. The guide calls fetching the rest of a thin change "hydration."
- A change notification often carries an id and what changed, not the fields a downstream agent needs. Ampersand's described path is to hydrate, transform and then deliver.
- Writing is a business action. Stages, required fields, assignment and permissions decide what may be written. Some customers want a batch to succeed or fail as a whole. Others want valid rows to land and failures reported. The guide says that choice has to be explicit.
- Production instances do not look like the vendor's test org. Backfills of large orgs run for hours and need a checkpoint that proves progress, or a healthy import and a stuck import look the same. The same HTTP status can mean a transient provider error or a missing permission. People leave, tokens get revoked, and a connection that could read contacts later fails when it first touches accounts. OAuth scopes and CRM permissions are different gates.
- Deploying code into the customer org, such as a Salesforce Apex trigger, can be easy to install and blocked on the way out by the customer's own test coverage.
- Between the record and the agent the preview draws five layers: the record, authorization, transport (rate limits, pagination, retries), shape (mapping and hydration), then the agent. Dead fields should be dropped. Source and time should be kept.
- One integration is an API call. A product that serves many customers needs a per-installation record of auth, schema, mappings, sync checkpoints and errors. The guide treats that management layer as infrastructure, including region separation, and says some failures still need a person.

Ampersand's connector docs match the book. The Salesforce CRM module supports read (backfill and incremental), write (including bulk write and delete), subscribe, and proxy calls. Account, Campaign, Case, Contact, Event, Lead, Opportunity, Product, Task and User are listed for all three, and the page says all custom objects are too, standard and custom fields included. Subscribe actions reuse a read object's field mapping. HubSpot adds an association-change event. The launch post says Salesforce has no native webhooks, so the practical stream is Change Data Capture, and that each customer needs isolated tokens and adaptive rate limits.

## Salesforce

Salesforce describes objects as tables and records as rows. Standard objects ship with the platform. Custom objects are defined in the org, including through the Metadata API. External objects point at data stored outside the org. The concepts page says Account is the central object for companies and organizations, and that an application only sees the objects the running user is allowed to see. Sharing rules and profile permissions are part of the model, not a layer beside it.

Custom fields and custom objects use an API name ending in `__c` (`Hire_Date__c`, `Issue__c`). A managed package adds a namespace prefix, so `name__c` becomes `prefix__name__c`. Uniqueness and case sensitivity are visible on describe and are not set by a normal data API call. A duplicate unique value returns `DUPLICATE_VALUE`. The custom-fields page lists Account, Campaign, Case, Contact, Contract, Event, Lead, Opportunity, Product2, Solution, Task and User as standard objects that accept custom fields. On that page, Lead, Task and Event accept custom fields and neither master-detail nor lookup relationships.

Describe global, `GET /services/data/vXX.X/sobjects/`, lists standard and custom objects and the maximum batch size. Describe on one object, `GET /services/data/vXX.X/sobjects/sObject/describe/`, returns fields, URLs and child relationships. Both honor `If-Modified-Since` with `304`. The describe-global page warns that the header also changes when org-wide permissions or profiles change, not only when that object's fields change. A cached schema can go stale because a person changed access.

API limits are per org, for a rolling 24 hours, not per user. Developer Edition is 15,000 calls. Enterprise Edition, and Professional with API access, is 100,000 plus licenses plus add-ons. The page's example is an Enterprise org with 15 Salesforce licenses: 115,000 calls. Unlimited and Performance use the same 100,000 base, with a Salesforce license counted at 5,000 calls. A full sandbox that is not created from a template is 5,000,000. REST, SOAP, Bulk API, Bulk API 2.0 and most Connect APIs count. Concurrent calls that last 20 seconds or longer are capped at 5 on Developer and trial orgs and 25 on production and sandboxes. REST and SOAP calls time out at 10 minutes, queries aside. The combined URI and headers on a REST call are limited to 16,384 bytes. The limits page points at Composite resources as the way to cut round trips. Usage is visible in the `Sforce-Limit-Info` header and at `/limits`.

Bulk API 2.0 is the documented path once a job is over 2,000 records. Bulk and Bulk 2.0 share 15,000 batches per rolling 24 hours and 150,000,000 uploaded records. In Bulk 2.0 only ingest jobs consume batches. A Bulk 2.0 ingest job is limited to 150 MB, and the page says to stay under about 100 MB of raw CSV because the body is base64-encoded. Results are kept for 7 days.

Change Data Capture publishes record changes. The allocations page says a change event message is at most 1 MB. A larger message is not delivered and is replaced by a gap event. The same page says the default cap on selected entities is 5, that an add-on removes that cap, and that delivery to Pub/Sub, CometD, empApi and event relays shares a rolling 24-hour allocation with high-volume platform events. The page's Unlimited example is 50,000 delivered events. Its default-allocations table lists 50,000, 25,000 and 10,000 for Performance and Unlimited, Enterprise, and Developer. Events are retained for 72 hours and can be resumed with a replay id. Apex triggers do not count against the delivery allocation. Exceeding it disconnects the subscriber.

## HubSpot

HubSpot's CRM guide defines objects, records, properties and associations. One object API covers the standard objects. The path parameter is an object type id: contacts `0-1`, companies `0-2`, deals `0-3`, tickets `0-5`. Activities are objects too: notes `0-46`, meetings `0-47`, calls `0-48`, emails `0-49`, tasks `0-27`. Custom objects use ids of the form `2-XXX`, discovered from the schemas API. Contacts, companies, deals, tickets and notes also accept a fully qualified name in some APIs.

Record ids (`hs_object_id`) are unique inside one object. A contact and a company can share the same id. Contacts also dedupe on email, companies on domain, and either object can gain a custom unique property. Batch upsert uses `idProperty`. Deals require `dealname`, `dealstage` and `pipeline` to create. Pipelines and stages are their own API.

Associations are separate from properties. They can be unlabeled or labeled (the guide's example is Decision maker). Association definitions, including custom labels, are a schema API. The associations guide's limits: Professional and Enterprise accounts get 500,000 association requests per day. Burst limits are 100 requests per 10 seconds on Free and Starter, and 150 on Professional and Enterprise. Batch read accepts 1,000 inputs. Batch create accepts 2,000.

Search is `POST` on the object search path. The search guide limits it to 5 requests per second per account, 200 records per page, 10,000 results for one query, a 3,000-character query, and at most five filter groups with six filters each and 18 filters in total. New and updated records can take a moment to appear. Archived records do not appear.

General app limits are separate and stricter APIs opt out of them. The usage guide says a publicly distributed OAuth app is limited to 110 requests per 10 seconds for each installing account, and that this excludes the CRM Search API. The API-limit add-on does not raise that public-app cap. Private apps, per the same page: Free and Starter 100 requests per 10 seconds per app and 250,000 per day per account; Professional 190 per 10 seconds and 625,000 per day; Enterprise 190 per 10 seconds and 1,000,000 per day. The daily cap is shared by private apps in the account. The burst cap is per app. A `429` body includes `policyName` of `DAILY` or the secondly policy. Daily reset follows the account time zone.

Webhooks are an app-level subscription, not an account-level one. The webhooks guide says the classic endpoints are for legacy public apps, that delivery is HTTPS, that settings can be cached for up to five minutes, and that HubSpot sends at most 10 concurrent requests per installing account, with up to 100 events in one request. Subscriptions need the matching CRM read scope. The guide also says webhooks can subscribe to CRM object events, including contacts, companies, deals, tickets, products and line items.

## Twenty, Attio, Folk, Pipedrive, Close

Twenty ships Companies, People, Opportunities, Tasks and Notes, and treats a custom object as a first-class object with the same REST and GraphQL endpoints, views, permissions and workflow triggers. There is no static API reference. Each workspace has its own schema. Records are under `/rest/{object}`. Schema changes go through `/rest/metadata/`. A record read can ask for `fields` and a relation `depth`. Omitting `fields` on an object with more than 200 readable fields returns a default of 200, standard fields before custom ones. Unknown fields and fields the role cannot read return 400.

Attio separates facts from process. Objects hold records (people and companies exist in every workspace; deal, user and workspace are optional). Lists hold entries that point at those records and can carry attributes that exist only for that process. People are enriched, and the people page says enriched values cannot be overridden by API users and that some enriched attributes are hidden from the API depending on the plan. Creating a person can create or match a company from the email domain. Deals, when an admin enables them, require name, stage and owner. Deals have no unique attribute by default. The deals page says to add one before asserting, because a non-unique match that hits two deals is rejected. The companies page says a custom attribute on Company cannot be given a unique constraint.

Folk scopes custom fields and custom object types to a group. Two groups can each have a Status field, or a Job Applications object, and they do not share a schema. People and companies are the contacts. An object links people, companies, or both. Writes go through `customFieldValues` keyed by group id. Select options are matched by label, and an unknown label on write creates an option.

Pipedrive's custom field keys are generated per account. The custom-fields page says the same name and type in two accounts still produce different `key` values, so a key cannot be copied between accounts. API v2 moves those keys under `custom_fields` instead of the v1 root-level hash keys. Leads inherit deal custom fields. Rate limits are a daily token budget: 30,000 base tokens times a plan multiplier (Lite 1, Growth 2, Premium 5, Ultimate 7) times seats, plus purchased top-ups, shared by the company. The page's sample costs include 2 tokens to get one entity, 20 to list, 10 to update, and 40 to search. A burst limit also applies per user on a 2-second window. An empty budget returns 429 until the next server-midnight reset.

Close inverts the Salesforce lead. A lead is the company or organization and contains contacts, tasks, opportunities and activities. Activities are calls, emails, notes, SMS and meetings. Custom fields sit on leads, contacts, opportunities and custom activities. `PUT` is a patch. The rate-limit page says limits are per endpoint group, per API key, and per organization, and that the organization limit is three times the per-key limit. The 20-versus-60 requests-per-second pair on that page is an illustration of the three-times rule, not a published universal cap. A 429 carries `RateLimit` and `retry-after`. The page says to wait for `rate_reset` rather than use a fixed backoff. Some endpoints can still 429 inside the window.

## What is good, and what hurts an agent

The useful ideas, across these systems:

- One graph of organizations, people, potential sales and activities, with every role reading a different view.
- Custom objects and fields that use the same API as standard ones. Twenty is the clearest statement of this. HubSpot's single object path is the same idea. Salesforce describe is the discovery tool, with the namespace and `__c` suffix as the tax.
- Associations as their own records, with labels, not only a lookup column. HubSpot and Attio both do this. Salesforce AccountContactRelation shows the same need on top of the lookup.
- History, ownership and a stage that can require data before it advances. That is the guide's reason to leave the spreadsheet.
- A stable external id, and an upsert that is idempotent. HubSpot's `idProperty` and Attio's assert-by-unique-attribute are the patterns. The id has to include the object type wherever ids are per object.
- Change streams plus a hydrate step. A thin event is a hint, not context.
- Checkpoints and a visible cursor on long imports. The guide's backfill lesson.
- An error category an agent can branch on, instead of a raw status code. The guide says raw provider errors also waste the agent's context.

The painful parts, for an engineer or an agent:

- The schema is owned by admins and drifts. Field names lie. Requiredness depends on stage, profile and validation rules the API does not always put in one document.
- The integration user does not see the CRM the admin sees. Describe and a successful OAuth handshake both overstate what the next call can do.
- Quotas are shared with every other tool in the org, and they are easy to spend by reading one record at a time or by searching. HubSpot search is a separate, much tighter budget. Salesforce counts Bulk calls against the same daily allocation as REST.
- Writes can start workflows, assignment rules and required-field failures. A confident agent that fills every field will clobber a rep's correction and can trip a validation rule it cannot see.
- Providers disagree on the words. Close's lead is a company. Salesforce's lead is a person who has not been converted. HubSpot has both a contact and a lead object (`0-136`). Pipedrive's custom field identity is an opaque hash. Attio will not let an API overwrite enriched facts.
- Lists and groups (Attio, Folk) are a second schema on top of the person. Copying "the contact" without the list loses the process.
- Test orgs do not reproduce production automations, and some of those automations only show up as an opaque status code.
- Event streams have their own caps, drop oversized messages into gap events, and still need a read before the agent can act.

## Implications for this CRM

The first slice should be the graph and the agent surface, not a Salesforce client. Standard objects are data, custom objects use the same calls, associations are labeled, activities are records with a source, and a context read returns one hop plus recent changes. Writes are partial, audited, and can require the revision the agent just read. External identity is provider, object type and external id, so a later import does not merge a HubSpot contact with a company that happens to share a number.

Live sync, webhooks and capture from Slack, email, GitHub and X are later. They need per-installation schema, checkpoints, a written batch policy, and a person in the loop when a provider error is really a permissions change. Those are the parts the guide says teams underestimate. They are also the parts that need approval before any live read.
