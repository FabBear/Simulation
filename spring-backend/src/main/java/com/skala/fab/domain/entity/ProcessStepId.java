package com.skala.fab.domain.entity;

import java.io.Serializable;
import java.util.Objects;

public class ProcessStepId implements Serializable {
    private String routeId;
    private Integer stepSeq;

    public ProcessStepId() {}

    public ProcessStepId(String routeId, Integer stepSeq) {
        this.routeId = routeId;
        this.stepSeq = stepSeq;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ProcessStepId that)) return false;
        return Objects.equals(routeId, that.routeId) && Objects.equals(stepSeq, that.stepSeq);
    }

    @Override
    public int hashCode() {
        return Objects.hash(routeId, stepSeq);
    }
}
