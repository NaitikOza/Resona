import type { ClinicalEvent } from "./types";
import { titleCase } from "./format";

const titles: Record<string, string> = {
  record_measurement: "Measurement recorded",
  record_observation: "Observation recorded",
  establish_iv_access: "IV access",
  perform_intubation: "Intubation",
  administer_medication: "Medication",
  administer_fluid: "Fluids",
  transfuse_blood_product: "Blood product",
  prepare_blood_product: "Blood product preparation",
  obtain_blood_product: "Blood product availability",
  consider_blood_product: "Blood product",
  obtain_imaging: "Imaging",
  obtain_test: "Test or lab",
  apply_equipment: "Equipment",
  communicate_or_consult: "Communication",
  reviewer_documented_event: "Documented event",
};

export function eventTitle(event: Pick<ClinicalEvent, "normalized_action" | "description" | "reviewer_status">): string {
  if (event.normalized_action === "reviewer_documented_event" || event.reviewer_status === "EDITED") {
    return event.description;
  }
  return titles[event.normalized_action] ?? titleCase(event.normalized_action);
}
