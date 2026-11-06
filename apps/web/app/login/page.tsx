import AuthForm from '@/components/AuthForm';
import { authMessageFromCode } from '@/lib/auth-errors';

function safeNext(value: string | string[] | undefined) {
  const path = Array.isArray(value) ? value[0] : value;
  return path?.startsWith('/') && !path.startsWith('//') ? path : '/workspace';
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <AuthForm mode="login" nextPath={safeNext(params.next)} initialError={authMessageFromCode(params.error)} />;
}
