import { PageHeader } from "../components/PageHeader";
import { PendingState } from "../components/States";
const shell = (title: string) => () => <div className="page"><PageHeader title={title} /><PendingState label="This page is not built yet" /></div>;
export const OperationsBoard = shell("Operations board");
export const IssueDetail = shell("Issue");
export const OperatorInbox = shell("Operator inbox");
export const CrewJobs = shell("Crew jobs");
export const CrewJob = shell("Job");
export const ResidentIntake = shell("Report a condition");
