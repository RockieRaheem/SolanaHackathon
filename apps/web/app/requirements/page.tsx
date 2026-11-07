import { Suspense } from 'react';
import RequirementsClient from './RequirementsClient';

export default function RequirementsPage() {
  return <Suspense fallback={<main className="page-state">Loading requirements...</main>}>
    <RequirementsClient />
  </Suspense>;
}
