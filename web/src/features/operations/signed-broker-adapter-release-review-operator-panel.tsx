import { useSignedBrokerAdapterReleaseReviewOperatorController } from './signed-broker-adapter-release-review-operator-controller';
import { SignedBrokerAdapterReleaseReviewOperatorView } from './signed-broker-adapter-release-review-operator-view';

type Locale = 'en' | 'zh';

export function SignedBrokerAdapterReleaseReviewOperatorPanel({
  locale,
}: {
  locale: Locale;
}) {
  const controller =
    useSignedBrokerAdapterReleaseReviewOperatorController(locale);
  return (
    <SignedBrokerAdapterReleaseReviewOperatorView
      controller={controller}
      locale={locale}
    />
  );
}
