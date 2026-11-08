import AuthForm from '@/components/AuthForm';
import { authMessageFromCode } from '@/lib/auth-errors';
import { safeNextPath } from '@/lib/auth-policy';


export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <AuthForm mode="login" nextPath={safeNextPath(Array.isArray(params.next) ? params.next[0] : params.next)} initialError={authMessageFromCode(params.error)} />;
}
