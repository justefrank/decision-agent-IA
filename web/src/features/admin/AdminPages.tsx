/** À implémenter : pages du back-office en lecture. */
function Stub({ name }: { name: string }) {
  return <p>{name}</p>;
}
export const AdminOverviewPage = () => <Stub name="Exploitation" />;
export const AdminAuditPage = () => <Stub name="Audit" />;
export const AdminEvalPage = () => <Stub name="Évaluation" />;
export const AdminFeedbackPage = () => <Stub name="Signalements" />;
export const AdminKpiPage = () => <Stub name="KPI" />;
export const AdminSemanticPage = () => <Stub name="Sémantique" />;
export const AdminSecurityPage = () => <Stub name="Sécurité" />;
export const AdminSettingsPage = () => <Stub name="Paramètres" />;
