// Enterprise pages (U-5a). installEnterprise registers them as children of upstream's "Platform"
// layout route at startup, so upstream's route table stays byte-identical to the pinned release.
// Moved verbatim from router/index.ts; only the component paths became relative to this directory.
import type { RouteRecordRaw } from "vue-router"

export const ENTERPRISE_ROUTE_PARENT = "Platform"

// Every route is named: installEnterprise skips names the router already has.
export const ENTERPRISE_ROUTES: (RouteRecordRaw & { name: string })[] = [
  {
    path: "knowledge-bases/:kbId/materials-wiki",
    name: "materialsWiki",
    redirect: (to) => ({
      name: "knowledgeBaseDetail",
      params: { kbId: to.params.kbId },
      query: { ...to.query, tab: "materials" },
    }),
    meta: { requiresInit: true, requiresAuth: true },
  },
  // Enterprise knowledge (S3d-3a): published releases of the caller's Spaces, read-only.
  {
    path: "enterprise",
    name: "enterpriseSpaces",
    component: () => import("./EnterpriseSpaces.vue"),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId",
    name: "enterpriseSpace",
    component: () => import("./EnterpriseSpace.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/changes",
    name: "enterpriseChanges",
    component: () => import("./EnterpriseChanges.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/spot-checks",
    name: "enterpriseSpotChecks",
    component: () => import("./EnterpriseSpotChecks.vue"),
    props: route => ({ spaceId: String(route.params.spaceId) }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/reviews",
    name: "enterpriseReviews",
    component: () => import("./EnterpriseReviews.vue"),
    props: route => ({ spaceId: String(route.params.spaceId) }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/confirmations",
    name: "enterpriseConfirmations",
    component: () => import("./EnterpriseConfirmations.vue"),
    props: route => ({ spaceId: String(route.params.spaceId) }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/graph",
    name: "enterpriseGraph",
    component: () => import("./EnterpriseGraph.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/concepts/:conceptKey",
    name: "enterpriseConcept",
    component: () => import("./EnterpriseConcept.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      conceptKey: String(route.params.conceptKey),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug",
    name: "enterpriseWikiPage",
    component: () => import("./EnterpriseWikiPage.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      entityId: String(route.params.entityId),
      pageType: String(route.params.pageType),
      pageSlug: String(route.params.pageSlug),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
  {
    path: "enterprise/:spaceId/entities/:entityId",
    name: "enterpriseEntity",
    component: () => import("./EnterpriseEntity.vue"),
    props: route => ({
      spaceId: String(route.params.spaceId),
      entityId: String(route.params.entityId),
      releaseId: typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined,
    }),
    meta: { requiresInit: true, requiresAuth: true }
  },
]
