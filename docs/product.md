# ShopRec

ShopRec helps small online stores recommend products from their own catalogs.
An optional partner network adds complementary products from other stores
after a purchase, only where the original store does not sell that category.

The recommendation widget is useful independently of the network. A store
can turn off partner participation and keep its own recommendations.

## Product rules

1. Own-store alternatives and complements come first.
2. A partner product must complement the selected product, be in stock and
   belong to a category absent from the source store's whole assortment.
3. Temporarily out-of-stock items still count as part of that assortment.
4. Both stores must participate and approve the partnership. An outgoing
   category restriction must be satisfied too.
5. Partner recommendations appear in a separate post-purchase scenario.
   The destination seller is visible before a visitor chooses to follow it.
6. No eligible candidate means no recommendation. The system does not fill
   empty space with unrelated items.

## Technical MVP

One pilot operator manages several stores. Catalogs, participation settings
and recorded click events persist in SQLite. The algorithm uses TF-IDF and
cosine similarity for alternatives, with separate compatibility rules for
complementary products. No purchase history or third-party AI key is needed.

The seeded stores and products are fictional. The MVP records actual
interactions with its interface; those records are not verified human visits,
orders, revenue or proof of incremental sales. Its simulated post-purchase
view does not process a payment or create a merchant order.

## First pilot

Recruit three stores with complementary assortments. Agree category mapping,
partnerships, placements, attribution and measurement before integration.
Evaluate own-store recommendations separately from partner referrals.
Participation does not guarantee equal traffic or commercial results.

The starting business hypothesis is a subscription for the core widget.
Pricing, willingness to share traffic, acquisition costs and retention still
need validation. The initial partner pilot has no money-based credit system
or automated advertising auction.
