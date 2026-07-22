import { Dashboard } from "./dashboard";

export const metadata = {
  title: "Deadside Command Center",
  description: "Painel operacional em tempo real do servidor Deadside.",
};

export default function Home() {
  return <Dashboard />;
}
