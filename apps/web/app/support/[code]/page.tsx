import SupportCampaign from './SupportCampaign';

export default async function SupportCampaignPage({params}:{params:Promise<{code:string}>}) {
  const {code}=await params;
  return <SupportCampaign code={code}/>;
}
