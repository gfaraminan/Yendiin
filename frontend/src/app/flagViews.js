export const resolveFlaggedViews = ({ altProducerUi = false, altStaffUi = false } = {}) => {
  const producerHomeView = altProducerUi ? "producerAlt" : "producer";
  const staffValidatorView = altStaffUi ? "qrValidatorAlt" : "qrValidator";
  const staffPosView = altStaffUi ? "staffPosAlt" : "staffPos";

  return {
    producerHomeView,
    staffValidatorView,
    staffPosView,
    isProducerView: (view) => view === "producer" || view === "producerAlt",
    isStaffValidatorView: (view) => view === "qrValidator" || view === "qrValidatorAlt",
    isStaffPosView: (view) => view === "staffPos" || view === "staffPosAlt",
  };
};
