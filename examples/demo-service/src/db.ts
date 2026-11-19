const databaseUrl = process.env.DATABASE_URL;
const { SENTRY_DSN, OTEL_ENDPOINT } = process.env;
const stripeKey = process.env["STRIPE_SECRET_KEY"];

// Dynamic access: the key is computed, so it is reported as unresolved.
const selected = process.env[process.env.PROFILE_NAME ?? "DATABASE_URL"];

export const config = {
  databaseUrl,
  sentryDsn: SENTRY_DSN,
  otelEndpoint: OTEL_ENDPOINT,
  stripeKey,
  selected,
};
