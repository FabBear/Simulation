package com.skala.fab.domain.repository;

import com.skala.fab.domain.entity.ProcessStepEntity;
import com.skala.fab.domain.entity.ProcessStepId;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProcessStepRepository extends JpaRepository<ProcessStepEntity, ProcessStepId> {}
