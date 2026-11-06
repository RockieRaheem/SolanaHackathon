import SupportCampaign from './SupportCampaign';
import SolanaContribution from '@/components/SolanaContribution';

export default async function SupportCampaignPage({params}:{params:Promise<{code:string}>}) {
  const {code}=await params;
  return <><SolanaContribution code={code}/><SupportCampaign code={code}/></>;
}
